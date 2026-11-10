using System.Globalization;
using System.IO;
using System.Text;
using SteelRidge.Core;
using UnityEditor;
using UnityEngine;

namespace SteelRidge.EditorTools
{
    /// <summary>
    /// 把契约导出成 contract.json —— 发给外包建模方的机读版本。
    /// 目的：外包按坐标建模，验收时只核数字，不争论比例。
    /// </summary>
    public static class MechaContractExport
    {
        [MenuItem("Steel Ridge/契约/导出 JSON（发给建模方）", false, 30)]
        public static void Export()
        {
            var c = SteelRidgeBlockout.EnsureContract();
            if (c == null) return;

            var issues = c.Validate();
            if (issues.Count > 0)
            {
                EditorUtility.DisplayDialog("契约自检未通过",
                    "先修契约再导出：\n\n• " + string.Join("\n• ", issues), "去修");
                return;
            }

            string json = Build(c);

            string inAssets = "Assets/_Project/Config/contract.json";
            SteelRidgeBlockout.EnsureFolder("Assets/_Project/Config");
            File.WriteAllText(ToAbsolute(inAssets), json);

            // 同步到工程根的 Contracts/ —— 与契约表 Markdown 放一起，一并发给建模方
            string sharedDir = "Contracts";
            if (!Directory.Exists(ToAbsolute(sharedDir))) Directory.CreateDirectory(ToAbsolute(sharedDir));
            string shared = Path.Combine(sharedDir, "contract.json");
            File.WriteAllText(ToAbsolute(shared), json);

            AssetDatabase.Refresh();
            Debug.Log($"[SteelRidge] 契约已导出：{inAssets} 和 {shared}\n{json}");

            EditorUtility.DisplayDialog("契约已导出",
                $"{inAssets}\n{shared}\n\n" +
                "发给建模方时，把 Contracts/ 整个目录打包：\n" +
                "• 尺寸与接口契约表.md（人读）\n" +
                "• contract.json（机读，可直接导入 Blender 脚本核尺寸）",
                "好");
        }

        static string ToAbsolute(string assetRelative) =>
            Path.GetFullPath(Path.Combine(Application.dataPath, "..", assetRelative));

        static string Build(MechaContract c)
        {
            var sb = new StringBuilder();
            var inv = CultureInfo.InvariantCulture;

            sb.AppendLine("{");
            sb.AppendLine("  \"schema\": \"steelridge.mecha.contract/1.0\",");
            sb.AppendLine($"  \"project\": \"钢脊：立于大地\",");
            sb.AppendLine($"  \"dcc_note\": \"单位米，Y 向上，机体正面 +Z；FBX 导出请保持 Scale 1.0，不要 Apply Unit Scale\",");
            sb.AppendLine($"  \"generated_by\": \"MechaContract v1.0\",");
            sb.AppendLine();

            sb.AppendLine("  \"derived\": {");
            sb.AppendLine($"    \"totalHeight\": {F(c.totalHeight, inv)},");
            sb.AppendLine($"    \"shoulderWidth\": {F(c.shoulderWidth, inv)},");
            sb.AppendLine($"    \"chestSocketY\": {F(c.chestSocketY, inv)},");
            sb.AppendLine($"    \"cockpitCenterY\": {F(c.CockpitCenterY, inv)},");
            sb.AppendLine($"    \"cockpitFloorY\": {F(c.CockpitFloorY, inv)},");
            sb.AppendLine($"    \"cockpitCeilingY\": {F(c.CockpitCeilingY, inv)},");
            sb.AppendLine($"    \"seatAnchorWorldY\": {F(c.SeatAnchorWorldY, inv)},");
            sb.AppendLine($"    \"shoulderY\": {F(c.shoulderY, inv)},");
            sb.AppendLine($"    \"elbowY\": {F(c.ElbowY, inv)},");
            sb.AppendLine($"    \"wristY\": {F(c.WristY, inv)},");
            sb.AppendLine($"    \"upperArmLength\": {F(c.upperArmLength, inv)},");
            sb.AppendLine($"    \"forearmLength\": {F(c.forearmLength, inv)},");
            sb.AppendLine($"    \"hatchCenterY\": {F(c.CockpitCenterY, inv)},");
            sb.AppendLine($"    \"hatchSize\": {{ \"height\": {F(c.hatchHeight, inv)}, \"width\": {F(c.hatchWidth, inv)} }}");
            sb.AppendLine("  },");
            sb.AppendLine();

            sb.AppendLine("  \"parts\": [");
            for (int i = 0; i < c.parts.Count; i++)
            {
                var p = c.parts[i];
                sb.Append($"    {{ \"id\": \"{p.id}\", \"label\": \"{p.label}\", \"bottom\": {F(p.bottom, inv)}, " +
                          $"\"top\": {F(p.top, inv)}, \"size\": [{F(p.size.x, inv)}, {F(p.size.y, inv)}, {F(p.size.z, inv)}], " +
                          $"\"mirrored\": {(p.mirrored ? "true" : "false")}, \"mirrorOffsetX\": {F(p.mirrorOffsetX, inv)} }}");
                sb.AppendLine(i < c.parts.Count - 1 ? "," : "");
            }
            sb.AppendLine("  ],");
            sb.AppendLine();

            sb.AppendLine("  \"sockets\": [");
            for (int i = 0; i < c.sockets.Count; i++)
            {
                var s = c.sockets[i];
                sb.Append($"    {{ \"name\": \"{s.name}\", \"parent\": \"{s.parent ?? ""}\", " +
                          $"\"localPosition\": [{F(s.localPosition.x, inv)}, {F(s.localPosition.y, inv)}, {F(s.localPosition.z, inv)}], " +
                          $"\"purpose\": \"{s.purpose}\" }}");
                sb.AppendLine(i < c.sockets.Count - 1 ? "," : "");
            }
            sb.AppendLine("  ],");
            sb.AppendLine();

            sb.AppendLine("  \"pivots\": [");
            for (int i = 0; i < c.pivots.Count; i++)
            {
                var p = c.pivots[i];
                sb.Append($"    {{ \"name\": \"{p.name}\", \"parent\": \"{p.parent}\", " +
                          $"\"localPosition\": [{F(p.localPosition.x, inv)}, {F(p.localPosition.y, inv)}, {F(p.localPosition.z, inv)}], " +
                          $"\"axis\": [{F(p.axis.x, inv)}, {F(p.axis.y, inv)}, {F(p.axis.z, inv)}], " +
                          $"\"minAngle\": {F(p.minAngle, inv)}, \"maxAngle\": {F(p.maxAngle, inv)}, \"note\": \"{p.note}\" }}");
                sb.AppendLine(i < c.pivots.Count - 1 ? "," : "");
            }
            sb.AppendLine("  ],");
            sb.AppendLine();

            sb.AppendLine("  \"cockpit\": {");
            sb.AppendLine($"    \"interior\": [{F(c.cockpitInterior.x, inv)}, {F(c.cockpitInterior.y, inv)}, {F(c.cockpitInterior.z, inv)}],");
            sb.AppendLine($"    \"seatPanHeight\": {F(c.seatPanHeight, inv)},");
            sb.AppendLine($"    \"seatBackHeight\": {F(c.seatBackHeight, inv)},");
            sb.AppendLine($"    \"eyeHeightFromFloor\": {F(c.eyeHeightFromFloor, inv)},");
            sb.AppendLine($"    \"eyeForwardOffset\": {F(c.eyeForwardOffset, inv)},");
            sb.AppendLine($"    \"dashDistanceFromEye\": [{F(c.dashNear, inv)}, {F(c.dashFar, inv)}],");
            sb.AppendLine($"    \"windowHalfHorizontal\": {F(c.windowHalfHorizontal, inv)},");
            sb.AppendLine($"    \"windowUp\": {F(c.windowUp, inv)},");
            sb.AppendLine($"    \"windowDown\": {F(c.windowDown, inv)},");
            sb.AppendLine($"    \"windowSideHalfHorizontal\": {F(c.windowSideHalfHorizontal, inv)}");
            sb.AppendLine("  }");
            sb.AppendLine("}");

            return sb.ToString();
        }

        static string F(float v, CultureInfo inv) => v.ToString("0.000", inv);
    }
}
