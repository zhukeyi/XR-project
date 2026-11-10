package com.steelspine.viewer;

import android.app.Activity;
import android.opengl.GLES20;
import android.opengl.GLSurfaceView;
import android.os.Bundle;
import android.widget.FrameLayout;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.FloatBuffer;

import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.opengles.GL10;

/**
 * 机体查看器（无引擎，纯 GLES 2.0）。
 *
 * 目的：在 PICO OS 6 模拟器里把 export_viewer_bin.py 导出的机体渲染出来，
 * 验证「几何管线 → Android → 屏上可见」这一段，而不是验证性能
 * （模拟器上限约 60 FPS、GPU 指标恒为 0，性能结论无效）。
 *
 * 注意：这是普通 2D 应用，在 OS 6 里以平面窗口呈现，不是沉浸式 OpenXR 会话。
 */
public class MainActivity extends Activity {

    private GLSurfaceView view;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);

        FrameLayout root = new FrameLayout(this);

        view = new GLSurfaceView(this);
        view.setEGLContextClientVersion(2);
        view.setRenderer(new MeshRenderer());
        view.setRenderMode(GLSurfaceView.RENDERMODE_CONTINUOUSLY);
        root.addView(view, new FrameLayout.LayoutParams(-1, -1));

        // 说明：GLSurfaceView 是独立 Surface，叠在上面的普通 View 不会合成进
        // 空间窗口的截图里（实测文字层始终不可见），所以信息只靠窗口标题承载。
        setContentView(root);
    }

    @Override
    protected void onResume() {
        super.onResume();
        view.onResume();
    }

    @Override
    protected void onPause() {
        super.onPause();
        view.onPause();
    }

    // ---------------------------------------------------------------- 渲染

    static final String VS =
            "uniform mat4 uMVP;\n" +
            "attribute vec3 aPos;\n" +
            "attribute vec3 aNrm;\n" +
            "varying vec3 vN;\n" +
            "void main() {\n" +
            "  vN = aNrm;\n" +
            "  gl_Position = uMVP * vec4(aPos, 1.0);\n" +
            "}\n";

    static final String FS =
            "precision mediump float;\n" +
            "varying vec3 vN;\n" +
            "uniform vec3 uColor;\n" +
            "void main() {\n" +
            "  vec3 n = normalize(vN);\n" +
            "  vec3 L = normalize(vec3(0.45, 0.80, 0.55));\n" +
            "  float d = max(dot(n, L), 0.0);\n" +
            "  float back = max(dot(n, normalize(vec3(-0.4, 0.2, -0.8))), 0.0);\n" +
            "  vec3 c = uColor * (0.22 + 0.78 * d) + uColor * 0.18 * back;\n" +
            "  gl_FragColor = vec4(c, 1.0);\n" +
            "}\n";

    class MeshRenderer implements GLSurfaceView.Renderer {

        private int prog, aPos, aNrm, uMVP, uColor;
        private FloatBuffer vbuf;
        private float[] colors;
        private int[] voffs;
        private int[] vcnts;
        private int partCount;
        private float centerX, centerY, centerZ, radius, sizeY;
        private float yaw = 28f, pitch = -6f;
        private int frames = 0;
        private float aspect = 1f;
        private long lastMs = 0L;

        @Override
        public void onSurfaceCreated(GL10 unused, EGLConfig cfg) {
            GLES20.glClearColor(0.043f, 0.075f, 0.110f, 1f);
            GLES20.glDisable(GLES20.GL_CULL_FACE);   // 先排除默认剔除
            GLES20.glDepthFunc(GLES20.GL_LEQUAL);

            prog = build();
            aPos = GLES20.glGetAttribLocation(prog, "aPos");
            aNrm = GLES20.glGetAttribLocation(prog, "aNrm");
            uMVP = GLES20.glGetUniformLocation(prog, "uMVP");
            uColor = GLES20.glGetUniformLocation(prog, "uColor");

            loadMesh();
        }

        private int build() {
            int v = compile(GLES20.GL_VERTEX_SHADER, VS);
            int f = compile(GLES20.GL_FRAGMENT_SHADER, FS);
            int p = GLES20.glCreateProgram();
            GLES20.glAttachShader(p, v);
            GLES20.glAttachShader(p, f);
            GLES20.glLinkProgram(p);
            int[] ok = new int[1];
            GLES20.glGetProgramiv(p, GLES20.GL_LINK_STATUS, ok, 0);
            if (ok[0] == 0) {
                throw new RuntimeException("link: " + GLES20.glGetProgramInfoLog(p));
            }
            return p;
        }

        private int compile(int type, String src) {
            int s = GLES20.glCreateShader(type);
            GLES20.glShaderSource(s, src);
            GLES20.glCompileShader(s);
            int[] ok = new int[1];
            GLES20.glGetShaderiv(s, GLES20.GL_COMPILE_STATUS, ok, 0);
            if (ok[0] == 0) {
                throw new RuntimeException("shader: " + GLES20.glGetShaderInfoLog(s));
            }
            return s;
        }

        /** 读 assets/hx07.bin：40 字节头 + partCount×60 分件表 + 顶点区。 */
        private void loadMesh() {
            try {
                InputStream in = getAssets().open("hx07.bin");
                java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream(1 << 19);
                byte[] chunk = new byte[1 << 16];
                int n;
                while ((n = in.read(chunk)) > 0) bo.write(chunk, 0, n);
                in.close();
                byte[] raw = bo.toByteArray();

                // ★ 必须是 direct buffer：GLES 的 glVertexAttribPointer 不接受堆缓冲，
                //   否则抛 IllegalArgumentException: Must use a native order direct Buffer
                ByteBuffer bb = ByteBuffer.allocateDirect(raw.length).order(ByteOrder.LITTLE_ENDIAN);
                bb.put(raw);
                bb.position(0);
                char[] magic = new char[4];
                for (int i = 0; i < 4; i++) magic[i] = (char) (bb.get() & 0xFF);
                if (!new String(magic).equals("SPV1")) {
                    throw new IOException("bad magic: " + new String(magic));
                }
                partCount = bb.getInt();
                int vcount = bb.getInt();
                bb.getInt();                       // indexCount（用不到，本模型索引是恒等）
                float cx = bb.getFloat(), cy = bb.getFloat(), cz = bb.getFloat();
                float sx = bb.getFloat(), sy = bb.getFloat(), sz = bb.getFloat();
                centerX = cx; centerY = cy; centerZ = cz;
                radius = Math.max(sx, Math.max(sy, sz)) * 0.5f;
                sizeY = sy;
                sizeY = sy;

                colors = new float[partCount * 3];
                voffs = new int[partCount];
                vcnts = new int[partCount];
                for (int i = 0; i < partCount; i++) {
                    bb.position(bb.position() + 32);
                    colors[i * 3] = bb.getFloat();
                    colors[i * 3 + 1] = bb.getFloat();
                    colors[i * 3 + 2] = bb.getFloat();
                    voffs[i] = bb.getInt();
                    vcnts[i] = bb.getInt();
                    bb.getInt();                   // ioff
                    bb.getInt();                   // icnt
                }

                // ★ 单条记录 = 名字 32 + rgb 3f(12) + 4×u32(16) = 60 字节（不是 44）
                bb.position(40 + partCount * 60);
                vbuf = bb.slice().order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer();
                vbuf.limit(vcount * 6);
                android.util.Log.i("HX07", "parsed parts=" + partCount + " vcount=" + vcount
                        + " vbufCap=" + vbuf.capacity() + " p0=" + voffs[0] + "/" + vcnts[0]
                        + " p1=" + voffs[1] + "/" + vcnts[1]
                        + " radius=" + radius + " centerY=" + centerY);
            } catch (IOException e) {
                throw new RuntimeException(e);
            }
        }

        @Override
        public void onSurfaceChanged(GL10 unused, int w, int h) {
            GLES20.glViewport(0, 0, w, h);
            aspect = h > 0 ? (float) w / (float) h : 1f;
        }

        @Override
        public void onDrawFrame(GL10 unused) {
            long now = System.currentTimeMillis();
            if (lastMs != 0) yaw += (now - lastMs) * 0.012f;
            lastMs = now;

            GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT | GLES20.GL_DEPTH_BUFFER_BIT);
            GLES20.glUseProgram(prog);

            // ★ 顺序必须是 P · T(后退) · R · T(居中)：
            //   先居中、再旋转、最后后退，模型才是自转；反过来会绕世界原点公转，
            //   34° 的偏航就能把模型甩出视锥（实测 NDC x = -1.15 被裁掉）。
            // 按模型实际高度与 FOV 反算距离，让机体占画面高度约 80%（换模型不用调参）
            final float fov = 42f;
            final float dist = (sizeY * 0.50f) / (float) Math.tan(Math.toRadians(fov * 0.5));
            float[] mvp = Mat.perspective(fov, aspect, Math.max(0.2f, dist * 0.05f), dist * 8f);
            mvp = Mat.mul(mvp, Mat.translate(0f, 0f, -dist));
            mvp = Mat.mul(mvp, Mat.rotateX(pitch));
            mvp = Mat.mul(mvp, Mat.rotateY(yaw));
            mvp = Mat.mul(mvp, Mat.translate(-centerX, -centerY, -centerZ));

            GLES20.glUniformMatrix4fv(uMVP, 1, false, mvp, 0);
            GLES20.glVertexAttribPointer(aPos, 3, GLES20.GL_FLOAT, false, 24, vbuf);
            GLES20.glVertexAttribPointer(aNrm, 3, GLES20.GL_FLOAT, false, 24,
                    vbuf.duplicate().position(3));
            GLES20.glEnableVertexAttribArray(aPos);
            GLES20.glEnableVertexAttribArray(aNrm);

            for (int i = 0; i < partCount; i++) {
                GLES20.glUniform3f(uColor, colors[i * 3], colors[i * 3 + 1], colors[i * 3 + 2]);
                GLES20.glDrawArrays(GLES20.GL_TRIANGLES, voffs[i], vcnts[i]);
            }
            if (frames++ == 3) {
                // 手算第一个顶点经过 mvp 后的裁剪坐标，判断是否在视锥内
                float vx = vbuf.get(0), vy = vbuf.get(1), vz = vbuf.get(2);
                float cx2 = mvp[0] * vx + mvp[4] * vy + mvp[8] * vz + mvp[12];
                float cy2 = mvp[1] * vx + mvp[5] * vy + mvp[9] * vz + mvp[13];
                float cz2 = mvp[2] * vx + mvp[6] * vy + mvp[10] * vz + mvp[14];
                float cw = mvp[3] * vx + mvp[7] * vy + mvp[11] * vz + mvp[15];
                android.util.Log.i("HX07", "v0=(" + vx + "," + vy + "," + vz + ") clip=("
                        + cx2 + "," + cy2 + "," + cz2 + "," + cw + ")");
                int err = GLES20.glGetError();
                android.util.Log.i("HX07", "prog=" + prog + " aPos=" + aPos + " aNrm=" + aNrm
                        + " uMVP=" + uMVP + " uColor=" + uColor + " aspect=" + aspect
                        + " glErr=" + err + " mvp0=" + mvp[0] + "," + mvp[5] + "," + mvp[11]);
            }
        }
    }

    // ---------------------------------------------------------------- 矩阵

    static final class Mat {
        static float[] perspective(float deg, float aspect, float near, float far) {
            float f = (float) (1.0 / Math.tan(deg * Math.PI / 360.0));
            return new float[]{
                    f / aspect, 0, 0, 0,
                    0, f, 0, 0,
                    0, 0, (far + near) / (near - far), -1,
                    0, 0, 2 * far * near / (near - far), 0
            };
        }

        static float[] translate(float x, float y, float z) {
            return new float[]{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1};
        }

        static float[] rotateX(float deg) {
            double r = Math.toRadians(deg), c = Math.cos(r), s = Math.sin(r);
            float cc = (float) c, ss = (float) s;
            return new float[]{1, 0, 0, 0, 0, cc, ss, 0, 0, -ss, cc, 0, 0, 0, 0, 1};
        }

        static float[] rotateY(float deg) {
            double r = Math.toRadians(deg), c = Math.cos(r), s = Math.sin(r);
            float cc = (float) c, ss = (float) s;
            return new float[]{cc, 0, -ss, 0, 0, 1, 0, 0, ss, 0, cc, 0, 0, 0, 0, 1};
        }

        static float[] mul(float[] a, float[] b) {
            float[] o = new float[16];
            for (int c = 0; c < 4; c++) {
                for (int r = 0; r < 4; r++) {
                    float s = 0;
                    for (int k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k];
                    o[c * 4 + r] = s;
                }
            }
            return o;
        }
    }
}
