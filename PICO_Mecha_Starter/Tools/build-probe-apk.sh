#!/usr/bin/env bash
# Tools/build-probe-apk.sh — 用已装的 Android SDK 手工打一个最小 APK
#
# 用途
#   在 Unity 的 Android Build Support 尚未就位时，先把
#   「打包 → 安装 → 启动 → 截图」这条端到端链路在 PICO 模拟器上跑通。
#   它验证的是工具链与模拟器，不是 Unity 本身——这个边界必须写清楚。
#
# 依赖
#   Android SDK：platforms/android-35（android.jar）、build-tools/35.0.0（aapt2/d8/zipalign/apksigner）
#   JDK：用 Android Studio 自带的 JBR（keytool/javac）
#
# 用法
#   ./Tools/build-probe-apk.sh                 # 产出 out/steelspine-probe.apk
#   ADB=... ./Tools/build-probe-apk.sh --install   # 打完直接装进当前 adb 设备
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
OUT="$ROOT/out/probe-apk"
PKG="com.steelspine.probe"
APP_ID="SteelSpineProbe"

export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export JAVA_HOME="${JAVA_HOME:-/Applications/Android Studio.app/Contents/jbr/Contents/Home}"
BT="$ANDROID_HOME/build-tools/35.0.0"
PLATFORM="$ANDROID_HOME/platforms/android-35/android.jar"
ADB="$ANDROID_HOME/platform-tools/adb"

for f in "$BT/aapt2" "$BT/d8" "$BT/apksigner" "$PLATFORM" "$JAVA_HOME/bin/keytool"; do
  [ -e "$f" ] || { echo "缺少依赖: $f"; exit 1; }
done

rm -rf "$OUT"
mkdir -p "$OUT/src/$PKG" "$OUT/res/values" "$OUT/classes" "$OUT/dex" "$OUT/gen"

cat > "$OUT/AndroidManifest.xml" <<XML
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="$PKG">
    <uses-sdk android:minSdkVersion="29" android:targetSdkVersion="35" />
    <application android:label="@string/app_name" android:hasCode="true">
        <activity android:name=".MainActivity"
                  android:exported="true"
                  android:screenOrientation="landscape">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
XML

cat > "$OUT/src/$PKG/MainActivity.java" <<'JAVA'
package com.steelspine.probe;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.widget.LinearLayout;
import android.widget.TextView;

/** 最小探针：只为验证 安装 → 启动 → 截图 这条链，不含任何业务逻辑。 */
public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setBackgroundColor(Color.parseColor("#0B1B2B"));

        TextView t1 = new TextView(this);
        t1.setText("钢脊 HX-07 · 链路探针");
        t1.setTextColor(Color.parseColor("#E8EEF8"));
        t1.setTextSize(34f);
        t1.setGravity(Gravity.CENTER);

        TextView t2 = new TextView(this);
        StringBuilder sb = new StringBuilder();
        sb.append("包装名  ").append(getPackageName()).append('\n');
        sb.append("设备    ").append(android.os.Build.MODEL).append('\n');
        sb.append("系统    Android ").append(android.os.Build.VERSION.RELEASE)
          .append("  (SDK ").append(android.os.Build.VERSION.SDK_INT).append(")\n");
        sb.append("ABI     ").append(android.os.Build.SUPPORTED_ABIS.length > 0
                ? android.os.Build.SUPPORTED_ABIS[0] : "?");
        t2.setText(sb.toString());
        t2.setTextColor(Color.parseColor("#7FB2E5"));
        t2.setTextSize(20f);
        t2.setGravity(Gravity.CENTER);
        t2.setPadding(0, 40, 0, 0);

        root.addView(t1);
        root.addView(t2);
        setContentView(root);
    }
}
JAVA

cat > "$OUT/res/values/strings.xml" <<'XML'
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">Steel Spine Probe</string>
</resources>
XML

echo "== 1/6 编译 Java =="
"$JAVA_HOME/bin/javac" -source 11 -target 11 -nowarn \
  -classpath "$PLATFORM" -d "$OUT/classes" "$OUT/src/$PKG/MainActivity.java" 2>&1 | grep -v "^Note:" || true

echo "== 2/6 dex =="
PKGPATH="${PKG//.//}"
"$BT/d8" --lib "$PLATFORM" --min-api 29 --output "$OUT/dex" \
  "$OUT/classes/$PKGPATH/"*.class

echo "== 3/6 编译资源 =="
"$BT/aapt2" compile --dir "$OUT/res" -o "$OUT/res.zip"

echo "== 4/6 链接资源 =="
"$BT/aapt2" link -o "$OUT/base.apk" -I "$PLATFORM" \
  --manifest "$OUT/AndroidManifest.xml" "$OUT/res.zip" --java "$OUT/gen"

echo "== 5/6 打入 classes.dex + 对齐 =="
( cd "$OUT/dex" && zip -q -X "$OUT/base.apk" classes.dex )
"$BT/zipalign" -f 4 "$OUT/base.apk" "$OUT/aligned.apk"

echo "== 6/6 签名 =="
KS="$OUT/debug.keystore"
"$JAVA_HOME/bin/keytool" -genkeypair -v -keystore "$KS" -storepass android \
  -keypass android -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 \
  -dname "CN=Steel Spine Probe, O=Local, C=CN" >/dev/null 2>&1
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:android --key-pass pass:android \
  --out "$OUT/$APP_ID.apk" "$OUT/aligned.apk"
"$BT/apksigner" verify --print-certs "$OUT/$APP_ID.apk" | head -3

ls -lh "$OUT/$APP_ID.apk"
echo "APK: $OUT/$APP_ID.apk"

if [ "${1:-}" = "--install" ]; then
  echo "== 安装到设备 =="
  "$ADB" install -r -g "$OUT/$APP_ID.apk"
  "$ADB" shell am start -n "$PKG/.MainActivity"
fi
