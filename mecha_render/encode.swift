// encode.swift — 用 macOS 原生 AVFoundation 把 PNG 序列编码为 H.264 MP4，并合并音轨
// 编译：swiftc -O -swift-version 5 encode.swift -o encode
// 用法：./encode <framesDir> <audioWav> <outMp4> <fps> <crf-ish quality: low|std|high>

import Foundation
import AVFoundation
import CoreGraphics
import ImageIO

func fail(_ msg: String) -> Never {
    FileHandle.standardError.write((msg + "\n").data(using: .utf8)!)
    exit(1)
}

let args = CommandLine.arguments
guard args.count >= 5 else {
    fail("usage: encode <framesDir> <audioWav> <outMp4> <fps> [quality]")
}
let framesDir = args[1]
let audioPath = args[2]
let outPath = args[3]
let fps = Int32(args[4]) ?? 24
let quality = args.count > 5 ? args[5] : "high"

let fm = FileManager.default
guard let entries = try? fm.contentsOfDirectory(atPath: framesDir) else {
    fail("cannot read \(framesDir)")
}
let frames = entries.filter { $0.hasSuffix(".png") }.sorted()
guard !frames.isEmpty else { fail("no png frames") }

// 读取首帧获取尺寸
guard let firstImg = CGImageSourceCreateWithURL(
        URL(fileURLWithPath: framesDir + "/" + frames[0]) as CFURL, nil),
      let firstCG = CGImageSourceCreateImageAtIndex(firstImg, 0, nil) else {
    fail("cannot read first frame")
}
let W = firstCG.width
let H = firstCG.height
print("frames=\(frames.count)  size=\(W)x\(H)  fps=\(fps)")

let tmpURL = URL(fileURLWithPath: NSTemporaryDirectory())
    .appendingPathComponent("encode_video_\(getpid()).mp4")
try? fm.removeItem(at: tmpURL)

let writer = try! AVAssetWriter(outputURL: tmpURL, fileType: .mp4)
let bitrate: Int
switch quality {
case "low":  bitrate = 4_000_000
case "std":  bitrate = 9_000_000
default:     bitrate = 16_000_000
}
let settings: [String: Any] = [
    AVVideoCodecKey: AVVideoCodecType.h264,
    AVVideoWidthKey: W,
    AVVideoHeightKey: H,
    AVVideoCompressionPropertiesKey: [
        AVVideoAverageBitRateKey: bitrate,
        AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel,
        AVVideoMaxKeyFrameIntervalKey: Int(fps) * 2,
        AVVideoAllowFrameReorderingKey: true,
    ],
]
let input = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
input.expectsMediaDataInRealTime = false
let adaptor = AVAssetWriterInputPixelBufferAdaptor(
    assetWriterInput: input,
    sourcePixelBufferAttributes: [
        kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
        kCVPixelBufferWidthKey as String: W,
        kCVPixelBufferHeightKey as String: H,
    ])
guard writer.canAdd(input) else { fail("cannot add input") }
writer.add(input)
guard writer.startWriting() else { fail("startWriting failed: \(String(describing: writer.error))") }
writer.startSession(atSourceTime: .zero)

let cs = CGColorSpaceCreateDeviceRGB()
let bmi = CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue

func makeBuffer(_ cg: CGImage) -> CVPixelBuffer? {
    guard let pool = adaptor.pixelBufferPool else { return nil }
    var px: CVPixelBuffer?
    guard CVPixelBufferPoolCreatePixelBuffer(nil, pool, &px) == kCVReturnSuccess,
          let buf = px else { return nil }
    CVPixelBufferLockBaseAddress(buf, [])
    defer { CVPixelBufferUnlockBaseAddress(buf, []) }
    guard let ctx = CGContext(data: CVPixelBufferGetBaseAddress(buf),
                              width: W, height: H, bitsPerComponent: 8,
                              bytesPerRow: CVPixelBufferGetBytesPerRow(buf),
                              space: cs, bitmapInfo: bmi) else { return nil }
    ctx.clear(CGRect(x: 0, y: 0, width: W, height: H))
    ctx.draw(cg, in: CGRect(x: 0, y: 0, width: W, height: H))
    return buf
}

var t0 = Date()
for (i, name) in frames.enumerated() {
    let url = URL(fileURLWithPath: framesDir + "/" + name)
    guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
          let cg = CGImageSourceCreateImageAtIndex(src, 0, nil) else {
        fail("cannot decode \(name)")
    }
    while !input.isReadyForMoreMediaData {
        usleep(1500)
    }
    guard let pb = makeBuffer(cg) else { fail("pixel buffer failed at \(i)") }
    let pts = CMTime(value: Int64(i), timescale: fps)
    if !adaptor.append(pb, withPresentationTime: pts) {
        fail("append failed at \(i): \(String(describing: writer.error))")
    }
    if i % 48 == 0 && i > 0 {
        let el = Date().timeIntervalSince(t0)
        print("  \(i)/\(frames.count)  \(String(format: "%.1f", el))s")
    }
}
input.markAsFinished()
let sem = DispatchSemaphore(value: 0)
writer.finishWriting { sem.signal() }
sem.wait()
if writer.status != .completed {
    fail("writer status=\(writer.status.rawValue) err=\(String(describing: writer.error))")
}
print("video track ok: \(tmpURL.path)")

// ---- 合并音轨
let finalURL = URL(fileURLWithPath: outPath)
try? fm.removeItem(at: finalURL)
let vAsset = AVURLAsset(url: tmpURL)
let aAsset = AVURLAsset(url: URL(fileURLWithPath: audioPath))
let comp = AVMutableComposition()
guard let vTracks = Optional(vAsset.tracks(withMediaType: .video)), let vSrc = vTracks.first else {
    // 回退：直接搬运无声视频
    try? fm.copyItem(at: tmpURL, to: finalURL)
    print("no video track? copied raw")
    exit(0)
}
let range = CMTimeRange(start: .zero, duration: vAsset.duration)
let vTrack = comp.addMutableTrack(withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid)!
try vTrack.insertTimeRange(range, of: vSrc, at: .zero)

if let aTracks = Optional(aAsset.tracks(withMediaType: .audio)), let aSrc = aTracks.first {
    let aDur = CMTimeMinimum(aAsset.duration, vAsset.duration)
    let aTrack = comp.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid)!
    try aTrack.insertTimeRange(CMTimeRange(start: .zero, duration: aDur), of: aSrc, at: .zero)
}

guard let exporter = AVAssetExportSession(asset: comp,
        presetName: AVAssetExportPresetHighestQuality) else { fail("no export session") }
exporter.outputURL = finalURL
exporter.outputFileType = .mp4
exporter.shouldOptimizeForNetworkUse = true
exporter.timeRange = range
let sem2 = DispatchSemaphore(value: 0)
exporter.exportAsynchronously { sem2.signal() }
sem2.wait()
if exporter.status != .completed {
    fail("export failed: \(String(describing: exporter.error))")
}
try? fm.removeItem(at: tmpURL)
let sz = (try? fm.attributesOfItem(atPath: outPath)[.size] as? Int) ?? 0
print("done -> \(outPath)  \(sz / 1024) KB")
