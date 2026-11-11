// DumpAndroidTools.cs — 诊断 Unity 到底从哪里读 Android 工具路径
//
// 背景：EditorPrefs 写入 JdkPath 后 batchmode 构建仍报 "JDK not found"。
// Unity 2022.3 把路径存在项目级 AndroidExternalToolsSettings.asset（ScriptableSingleton），
// 而不是 EditorPrefs。本脚本用反射把该类型的字段/属性/实例打出来，并尝试写入正确字段。
//
// 用法
//   Unity -batchmode -quit -projectPath <proj> -executeMethod SteelSpine.EditorTools.DumpAndroidTools.Run

using System;
using System.Reflection;
using UnityEditor;
using UnityEngine;

namespace SteelSpine.EditorTools
{
    public static class DumpAndroidTools
    {
        const string Jdk = "/Users/zhukeyi/.local/jdk/jdk11";
        const string Sdk = "/Users/zhukeyi/Library/Android/sdk";
        const string Ndk = "/Users/zhukeyi/Library/Android/sdk/ndk/23.1.7779620";

        public static void Run()
        {
            var type = FindType("UnityEditor.Android.AndroidExternalToolsSettings");
            if (type == null)
            {
                Debug.LogError("[DumpTools] 找不到 AndroidExternalToolsSettings 类型");
                EditorApplication.Exit(1);
                return;
            }

            Debug.Log("[DumpTools] 类型: " + type.FullName + "  asm=" + type.Assembly.GetName().Name);

            const BindingFlags F = BindingFlags.Public | BindingFlags.NonPublic |
                                   BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;

            foreach (var f in type.GetFields(F))
                Debug.Log("[DumpTools] FIELD " + f.FieldType.Name + " " + f.Name);
            foreach (var p in type.GetProperties(F))
                Debug.Log("[DumpTools] PROP " + p.PropertyType.Name + " " + p.Name
                          + " get=" + (p.GetGetMethod(true) != null)
                          + " set=" + (p.GetSetMethod(true) != null));

            object inst = null;
            var instProp = type.GetProperty("instance", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static);
            if (instProp != null) inst = instProp.GetValue(null);
            if (inst == null)
            {
                var instField = type.GetField("s_Instance", BindingFlags.NonPublic | BindingFlags.Static);
                if (instField != null) inst = instField.GetValue(null);
            }
            Debug.Log("[DumpTools] instance = " + (inst == null ? "null" : type.Name));

            if (inst != null)
            {
                TrySet(type, inst, "jdkRootPath", Jdk);
                TrySet(type, inst, "sdkRootPath", Sdk);
                TrySet(type, inst, "ndkRootPath", Ndk);
                TrySet(type, inst, "m_JdkRoot", Jdk);
                TrySet(type, inst, "m_SdkRoot", Sdk);
                TrySet(type, inst, "m_NdkRoot", Ndk);

                EditorUtility.SetDirty((UnityEngine.Object)inst);
                AssetDatabase.SaveAssets();

                // 读回验证
                foreach (var n in new[] { "jdkRootPath", "m_JdkRoot", "sdkRootPath", "m_SdkRoot" })
                {
                    var p = type.GetProperty(n, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
                    if (p != null && p.CanRead)
                        Debug.Log("[DumpTools] READ " + n + " = " + p.GetValue(inst));
                    var f = type.GetField(n, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
                    if (f != null)
                        Debug.Log("[DumpTools] READ " + n + " = " + f.GetValue(inst));
                }
            }

            EditorApplication.Exit(0);
        }

        static void TrySet(Type t, object inst, string name, string value)
        {
            var p = t.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
            if (p != null && p.CanWrite) { p.SetValue(inst, value); Debug.Log("[DumpTools] SET prop " + name); return; }
            var f = t.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
            if (f != null) { f.SetValue(inst, value); Debug.Log("[DumpTools] SET field " + name); }
        }

        static Type FindType(string fullName)
        {
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                var t = asm.GetType(fullName, false);
                if (t != null) return t;
            }
            try
            {
                return Assembly.Load("UnityEditor.Android.Extensions").GetType(fullName);
            }
            catch { return null; }
        }
    }
}
