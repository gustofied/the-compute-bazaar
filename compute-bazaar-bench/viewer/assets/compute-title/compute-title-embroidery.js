const WORDS = [
  {
    word: "THE",
    cx: 0.16,
    cy: 0.3,
    scale: 0.28,
    rotDeg: -4,
    fill: [0.718, 0.816, 0.482],
    ink: [0.078, 0.125, 0.153],
    border: [0.937, 0.929, 0.894],
  },
  {
    word: "COMPUTE",
    cx: 0.52,
    cy: 0.3,
    scale: 0.3,
    rotDeg: 1,
    fill: [0.569, 0.682, 0.796],
    ink: [0.078, 0.125, 0.153],
    border: [0.937, 0.929, 0.894],
  },
  {
    word: "BAZAAR",
    cx: 0.52,
    cy: 0.7,
    scale: 0.28,
    rotDeg: -2,
    fill: [0.953, 0.784, 0.533],
    ink: [0.078, 0.125, 0.153],
    border: [0.937, 0.929, 0.894],
  },
];

const FABRIC = [0.937, 0.929, 0.894];
const WEAVE_URL = new URL(
  "./assets/embroidery-weave.webp",
  import.meta.url,
).href;
const REST_ANGLE = (73 * Math.PI) / 180;
const LIGHT_Z = 0.55;
const WEAVE_SCALE = 15;

const EMB_VERT = `
attribute vec2 aPosition;
attribute vec2 aUV;
varying vec2 vUV;
void main() {
  vUV = aUV;
  gl_Position = vec4(aPosition, 0.0, 1.0);
}
`;

const EMB_FRAG = `
precision highp float;

varying vec2 vUV;

uniform sampler2D uArt;
uniform sampler2D uField;
uniform sampler2D uWeave;
uniform vec2  uTexel;
uniform vec2  uLight;
uniform float uLightZ;
uniform vec2  uWash;
uniform float uHover;
uniform float uPress;
uniform vec2  uPressPos;
uniform float uAspect;
uniform vec3  uFabric;
uniform float uDepth;
uniform float uWeaveScale;

float hash(vec2 p) {
  p = mod(p, 137.0);
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

float noise(vec2 p) {
  p = mod(p, 137.0);
  vec2 i = floor(p);
  vec2 f = fract(p);
  float a = hash(i);
  float b = hash(i + vec2(1.0, 0.0));
  float c = hash(i + vec2(0.0, 1.0));
  float d = hash(i + vec2(1.0, 1.0));
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

float weaveAt(vec2 uv) {
  return texture2D(
    uWeave,
    fract(uv * vec2(uAspect, 1.0) * uWeaveScale)
  ).r;
}

void main() {
  vec2 uv = vUV;
  vec2 texel = uTexel;
  vec4 fld = texture2D(uField, uv);
  float cover = fld.r;
  float inkM = fld.g;
  float ringM = fld.b;
  float stitchAng = fld.a * 3.14159;

  vec2 dp = uv * vec2(uAspect, 1.0);
  float bw = weaveAt(uv + vec2(0.37, 0.11));
  float blotch = noise(dp * 3.0) * 0.1 + noise(dp * 7.0) * 0.05;
  vec3 fabric = uFabric * (0.72 + bw * 0.6 + (blotch - 0.075));
  fabric += (noise(dp * 240.0) - 0.5) * 0.025;
  vec3 col = fabric;

  float pdist = distance(
    uv * vec2(uAspect, 1.0),
    uPressPos * vec2(uAspect, 1.0)
  );
  float pressLocal = uPress * (1.0 - smoothstep(0.0, 0.5, pdist));
  float lift = 1.0 - pressLocal * 0.85;
  vec2 shOff = vec2(6.0, -6.0) * texel * lift;
  float shc = texture2D(uField, uv - shOff).r;
  float shadowAlpha = smoothstep(0.2, 0.8, shc)
    * (1.0 - smoothstep(0.0, 0.25, cover))
    * mix(0.32, 0.18, pressLocal);

  if (cover < 0.004) {
    gl_FragColor = vec4(vec3(0.055, 0.075, 0.067), shadowAlpha);
    return;
  }

  float w0 = weaveAt(uv);
  float wL = weaveAt(uv - vec2(1.0, 0.0) * texel);
  float wR = weaveAt(uv + vec2(1.0, 0.0) * texel);
  float wD = weaveAt(uv - vec2(0.0, 1.0) * texel);
  float wU = weaveAt(uv + vec2(0.0, 1.0) * texel);
  vec2 wslope = vec2(wR - wL, wU - wD) * 22.0;
  vec3 Nw = normalize(vec3(-wslope.x, -wslope.y, 1.0));

  float cL = texture2D(uField, uv - vec2(1.0, 0.0) * texel).r;
  float cR = texture2D(uField, uv + vec2(1.0, 0.0) * texel).r;
  float cD = texture2D(uField, uv - vec2(0.0, 1.0) * texel).r;
  float cU = texture2D(uField, uv + vec2(0.0, 1.0) * texel).r;
  vec2 pslope = vec2(cR - cL, cU - cD) * uDepth * 16.0;
  vec3 Np = vec3(-pslope.x, -pslope.y, 1.0);
  float bevel = clamp(length(pslope), 0.0, 1.0);
  vec3 N = normalize(Np + Nw * 2.0);

  vec3 L = normalize(vec3(uLight, uLightZ));
  float diff = dot(N, L);
  float hi = pow(max(diff, 0.0), 1.25);
  float sh = pow(max(-diff, 0.0), 1.1);
  vec3 art = texture2D(uArt, uv).rgb;
  vec3 c = art * (0.72 + w0 * 0.6);

  float sc = cos(stitchAng);
  float ss = sin(stitchAng);
  float across = dp.x * ss - dp.y * sc;
  float rows = across * 260.0;
  float ridge = 0.5 + 0.5 * sin(mod(rows, 6.2831853));
  ridge = pow(ridge, 1.4);
  float jit = noise(
    vec2(floor(rows), (dp.x * sc + dp.y * ss) * 90.0)
  ) * 0.25;
  float satinShade = mix(
    0.82,
    1.14,
    clamp(ridge + jit * ridge, 0.0, 1.0)
  );

  float clothFace = cover * (1.0 - inkM);
  c *= mix(1.0, satinShade, clothFace * 0.9 + ringM * 0.6);
  c *= 1.0 - inkM * 0.05;
  c += hi * 0.46 * (0.5 + bevel * 0.5);
  c -= sh * 0.36;

  float edge = 1.0 - smoothstep(0.0, 0.32, cover);
  c *= 1.0 - edge * 0.28 * cover;
  c += (noise(dp * 380.0) - 0.5) * 0.045;

  if (uHover > 0.001) {
    float d = distance(dp, uWash * vec2(uAspect, 1.0));
    float halo = 1.0 - smoothstep(0.0, 0.42, d);
    float crown = smoothstep(0.72, 1.0, ridge);
    float glint = halo * halo * (0.35 + crown * 0.9) * uHover;
    c += glint * 0.16 * cover;
  }

  c *= 1.0 - pressLocal * 0.16 * cover;
  c = clamp(c, 0.0, 1.0);
  float aa = smoothstep(0.06, 0.2, cover);
  gl_FragColor = vec4(mix(col, c, aa), max(aa, shadowAlpha));
}
`;

export function setupComputeTitleEmbroidery() {
  const host = document.querySelector("[data-compute-embroidery]");
  if (!host) return;

  const reducedMotion = window.matchMedia(
    "(prefers-reduced-motion: reduce)",
  ).matches;
  const embroidery = new Embroidery(host, '"Geist", "Avenir Next", sans-serif');
  if (!embroidery.ok) {
    host.dataset.embroideryFallback = "true";
    return;
  }

  let visible = false;
  const updateActivity = () => {
    if (document.hidden || !visible || reducedMotion) {
      embroidery.stop();
      if (reducedMotion) embroidery.renderStill();
      return;
    }
    embroidery.start();
  };

  const resizeObserver = new ResizeObserver(() => embroidery.resize());
  resizeObserver.observe(host);

  const intersectionObserver = new IntersectionObserver(
    (entries) => {
      visible = Boolean(entries[0]?.isIntersecting);
      updateActivity();
    },
    { rootMargin: "120px 0px" },
  );
  intersectionObserver.observe(host);

  const onVisibility = () => updateActivity();
  const onEnter = () => {
    if (!reducedMotion) embroidery.setHover(1);
  };
  const onLeave = () => embroidery.setHover(0);
  const onPress = (event) => {
    if (reducedMotion) return;
    const bounds = host.getBoundingClientRect();
    embroidery.pressTap(
      (event.clientX - bounds.left) / bounds.width,
      (event.clientY - bounds.top) / bounds.height,
    );
  };

  document.addEventListener("visibilitychange", onVisibility);
  host.addEventListener("pointerenter", onEnter);
  host.addEventListener("pointerleave", onLeave);
  host.addEventListener("pointerdown", onPress);

  window.addEventListener(
    "pagehide",
    () => {
      resizeObserver.disconnect();
      intersectionObserver.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      host.removeEventListener("pointerenter", onEnter);
      host.removeEventListener("pointerleave", onLeave);
      host.removeEventListener("pointerdown", onPress);
      embroidery.destroy();
    },
    { once: true },
  );
}

class Embroidery {
  constructor(host, fontFamily) {
    this.host = host;
    this.fontFamily = fontFamily;
    this.canvas = document.createElement("canvas");
    this.canvas.setAttribute("aria-hidden", "true");
    Object.assign(this.canvas.style, {
      position: "absolute",
      inset: "0",
      width: "100%",
      height: "100%",
      display: "block",
      opacity: "0",
    });
    host.append(this.canvas);

    this.gl = this.canvas.getContext("webgl", {
      alpha: true,
      antialias: false,
      premultipliedAlpha: false,
    });
    this.program = null;
    this.locations = {};
    this.quad = null;
    this.artTexture = null;
    this.fieldTexture = null;
    this.weaveTexture = null;
    this.textureWidth = 1;
    this.textureHeight = 1;
    this.frameRequest = 0;
    this.running = false;
    this.awake = false;
    this.width = 0;
    this.height = 0;
    this.dpr = 1;
    this.builtWidth = 0;
    this.builtHeight = 0;
    this.builtFont = "";
    this.buildScheduled = 0;
    this.destroyed = false;
    this.painted = false;
    this.hover = 0;
    this.hoverTarget = 0;
    this.washX = 0.5;
    this.washY = 0.5;
    this.targetWashX = 0.5;
    this.targetWashY = 0.5;
    this.press = 0;
    this.pressVelocity = 0;
    this.pressKick = 0;
    this.pressX = 0.5;
    this.pressY = 0.5;
    this.ok = false;

    if (!this.gl) return;

    try {
      this.program = this.buildProgram(EMB_VERT, EMB_FRAG);
    } catch (error) {
      console.warn("Compute title embroidery could not initialize", error);
      this.gl = null;
      return;
    }

    const uniforms = [
      "uArt",
      "uField",
      "uWeave",
      "uTexel",
      "uLight",
      "uLightZ",
      "uWash",
      "uHover",
      "uPress",
      "uPressPos",
      "uAspect",
      "uFabric",
      "uDepth",
      "uWeaveScale",
    ];
    uniforms.forEach((name) => {
      this.locations[name] = this.gl.getUniformLocation(this.program, name);
    });

    const position = this.gl.getAttribLocation(this.program, "aPosition");
    const uv = this.gl.getAttribLocation(this.program, "aUV");
    const data = new Float32Array([
      -1, -1, 0, 1,
      1, -1, 1, 1,
      -1, 1, 0, 0,
      1, 1, 1, 0,
    ]);
    this.quad = this.gl.createBuffer();
    this.gl.bindBuffer(this.gl.ARRAY_BUFFER, this.quad);
    this.gl.bufferData(this.gl.ARRAY_BUFFER, data, this.gl.STATIC_DRAW);
    this.gl.useProgram(this.program);
    this.gl.enableVertexAttribArray(position);
    this.gl.vertexAttribPointer(position, 2, this.gl.FLOAT, false, 16, 0);
    this.gl.enableVertexAttribArray(uv);
    this.gl.vertexAttribPointer(uv, 2, this.gl.FLOAT, false, 16, 8);
    this.gl.clearColor(0, 0, 0, 0);

    this.resize();
    this.weaveTexture = this.placeholderTexture([150, 150, 150, 255]);
    this.loadWeave();
    this.buildSceneNow();
    this.host.addEventListener("pointermove", this.onMove);
    this.ok = true;
  }

  onMove = (event) => {
    const bounds = this.host.getBoundingClientRect();
    this.targetWashX = (event.clientX - bounds.left) / bounds.width;
    this.targetWashY = (event.clientY - bounds.top) / bounds.height;
    this.wake();
  };

  buildProgram(vertexSource, fragmentSource) {
    const compile = (type, source) => {
      const shader = this.gl.createShader(type);
      this.gl.shaderSource(shader, source);
      this.gl.compileShader(shader);
      if (!this.gl.getShaderParameter(shader, this.gl.COMPILE_STATUS)) {
        throw new Error(this.gl.getShaderInfoLog(shader) || "Shader failed");
      }
      return shader;
    };
    const program = this.gl.createProgram();
    this.gl.attachShader(
      program,
      compile(this.gl.VERTEX_SHADER, vertexSource),
    );
    this.gl.attachShader(
      program,
      compile(this.gl.FRAGMENT_SHADER, fragmentSource),
    );
    this.gl.linkProgram(program);
    if (!this.gl.getProgramParameter(program, this.gl.LINK_STATUS)) {
      throw new Error(this.gl.getProgramInfoLog(program) || "Link failed");
    }
    return program;
  }

  placeholderTexture(rgba) {
    const texture = this.gl.createTexture();
    this.gl.bindTexture(this.gl.TEXTURE_2D, texture);
    this.gl.texImage2D(
      this.gl.TEXTURE_2D,
      0,
      this.gl.RGBA,
      1,
      1,
      0,
      this.gl.RGBA,
      this.gl.UNSIGNED_BYTE,
      new Uint8Array(rgba),
    );
    this.gl.texParameteri(
      this.gl.TEXTURE_2D,
      this.gl.TEXTURE_MIN_FILTER,
      this.gl.LINEAR,
    );
    this.gl.texParameteri(
      this.gl.TEXTURE_2D,
      this.gl.TEXTURE_MAG_FILTER,
      this.gl.LINEAR,
    );
    return texture;
  }

  loadWeave() {
    const image = new Image();
    image.onload = () => {
      if (!this.gl || !this.weaveTexture || this.destroyed) return;
      this.gl.bindTexture(this.gl.TEXTURE_2D, this.weaveTexture);
      this.gl.pixelStorei(this.gl.UNPACK_FLIP_Y_WEBGL, true);
      this.gl.texImage2D(
        this.gl.TEXTURE_2D,
        0,
        this.gl.RGBA,
        this.gl.RGBA,
        this.gl.UNSIGNED_BYTE,
        image,
      );
      this.gl.texParameteri(
        this.gl.TEXTURE_2D,
        this.gl.TEXTURE_WRAP_S,
        this.gl.REPEAT,
      );
      this.gl.texParameteri(
        this.gl.TEXTURE_2D,
        this.gl.TEXTURE_WRAP_T,
        this.gl.REPEAT,
      );
      this.gl.texParameteri(
        this.gl.TEXTURE_2D,
        this.gl.TEXTURE_MIN_FILTER,
        this.gl.LINEAR,
      );
      this.gl.texParameteri(
        this.gl.TEXTURE_2D,
        this.gl.TEXTURE_MAG_FILTER,
        this.gl.LINEAR,
      );
      this.gl.pixelStorei(this.gl.UNPACK_FLIP_Y_WEBGL, false);
      if (!this.running) this.render();
    };
    image.src = WEAVE_URL;
  }

  setHover(value) {
    this.hoverTarget = Math.max(0, Math.min(1, value));
    this.wake();
  }

  pressTap(x = 0.5, y = 0.5) {
    this.pressX = Math.max(0, Math.min(1, x));
    this.pressY = Math.max(0, Math.min(1, y));
    this.pressKick = 1;
    this.wake();
  }

  wake() {
    if (this.awake && !this.running) this.start();
    else if (!this.running) this.render();
  }

  resize() {
    const bounds = this.host.getBoundingClientRect();
    this.dpr = Math.min(2, window.devicePixelRatio || 1);
    this.width = bounds.width;
    this.height = bounds.height;
    const canvasWidth = Math.max(1, Math.round(this.width * this.dpr));
    const canvasHeight = Math.max(1, Math.round(this.height * this.dpr));
    if (
      this.canvas.width !== canvasWidth ||
      this.canvas.height !== canvasHeight
    ) {
      this.canvas.width = canvasWidth;
      this.canvas.height = canvasHeight;
      this.gl?.viewport(0, 0, canvasWidth, canvasHeight);
      this.scheduleBuild();
    }
  }

  maskSize() {
    const maximumWidth = 1100;
    const width = Math.max(
      2,
      Math.min(maximumWidth, Math.round(this.width * this.dpr)),
    );
    const height = Math.max(
      2,
      Math.round(width * (this.height / Math.max(1, this.width))),
    );
    return [width, height];
  }

  scheduleBuild() {
    if (!this.gl || this.destroyed) return;
    const [width, height] = this.maskSize();
    if (
      width === this.builtWidth &&
      height === this.builtHeight &&
      this.fontFamily === this.builtFont
    ) {
      return;
    }
    if (this.buildScheduled) return;
    const run = () => {
      this.buildScheduled = 0;
      this.buildSceneNow();
    };
    this.buildScheduled = window.requestIdleCallback
      ? window.requestIdleCallback(run, { timeout: 200 })
      : window.setTimeout(run, 0);
  }

  async buildSceneNow() {
    if (!this.gl || this.destroyed) return;
    if (this.buildScheduled) {
      if (window.cancelIdleCallback) {
        window.cancelIdleCallback(this.buildScheduled);
      } else {
        window.clearTimeout(this.buildScheduled);
      }
      this.buildScheduled = 0;
    }
    if (document.fonts?.ready) await document.fonts.ready;
    const [width, height] = this.maskSize();
    this.builtWidth = width;
    this.builtHeight = height;
    this.builtFont = this.fontFamily;
    const scene = makeScene(width, height, this.fontFamily);
    if (!this.gl || this.destroyed) return;
    if (!this.artTexture) this.artTexture = this.gl.createTexture();
    if (!this.fieldTexture) this.fieldTexture = this.gl.createTexture();
    this.uploadCanvas(this.artTexture, scene.art);
    this.uploadPixels(this.fieldTexture, scene.field);
    this.textureWidth = scene.field.width;
    this.textureHeight = scene.field.height;
    if (!this.running) this.render();
  }

  uploadCanvas(texture, canvas) {
    this.gl.bindTexture(this.gl.TEXTURE_2D, texture);
    this.gl.texParameteri(
      this.gl.TEXTURE_2D,
      this.gl.TEXTURE_MIN_FILTER,
      this.gl.LINEAR,
    );
    this.gl.texParameteri(
      this.gl.TEXTURE_2D,
      this.gl.TEXTURE_MAG_FILTER,
      this.gl.LINEAR,
    );
    this.gl.texParameteri(
      this.gl.TEXTURE_2D,
      this.gl.TEXTURE_WRAP_S,
      this.gl.CLAMP_TO_EDGE,
    );
    this.gl.texParameteri(
      this.gl.TEXTURE_2D,
      this.gl.TEXTURE_WRAP_T,
      this.gl.CLAMP_TO_EDGE,
    );
    this.gl.pixelStorei(this.gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    this.gl.texImage2D(
      this.gl.TEXTURE_2D,
      0,
      this.gl.RGBA,
      this.gl.RGBA,
      this.gl.UNSIGNED_BYTE,
      canvas,
    );
  }

  uploadPixels(texture, pixels) {
    this.gl.bindTexture(this.gl.TEXTURE_2D, texture);
    this.gl.texParameteri(
      this.gl.TEXTURE_2D,
      this.gl.TEXTURE_MIN_FILTER,
      this.gl.LINEAR,
    );
    this.gl.texParameteri(
      this.gl.TEXTURE_2D,
      this.gl.TEXTURE_MAG_FILTER,
      this.gl.LINEAR,
    );
    this.gl.texParameteri(
      this.gl.TEXTURE_2D,
      this.gl.TEXTURE_WRAP_S,
      this.gl.CLAMP_TO_EDGE,
    );
    this.gl.texParameteri(
      this.gl.TEXTURE_2D,
      this.gl.TEXTURE_WRAP_T,
      this.gl.CLAMP_TO_EDGE,
    );
    this.gl.pixelStorei(this.gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    this.gl.texImage2D(
      this.gl.TEXTURE_2D,
      0,
      this.gl.RGBA,
      pixels.width,
      pixels.height,
      0,
      this.gl.RGBA,
      this.gl.UNSIGNED_BYTE,
      pixels.data,
    );
  }

  start() {
    if (!this.ok) return;
    this.awake = true;
    if (this.running) return;
    this.running = true;
    this.resize();
    const loop = () => {
      if (!this.running) return;
      this.frame();
      this.frameRequest = requestAnimationFrame(loop);
    };
    this.frameRequest = requestAnimationFrame(loop);
  }

  stop() {
    this.awake = false;
    this.pause();
  }

  pause() {
    this.running = false;
    if (this.frameRequest) cancelAnimationFrame(this.frameRequest);
    this.frameRequest = 0;
  }

  frame() {
    const smoothing = 0.12;
    this.hover += (this.hoverTarget - this.hover) * smoothing;
    this.washX += (this.targetWashX - this.washX) * smoothing;
    this.washY += (this.targetWashY - this.washY) * smoothing;
    this.pressKick *= 0.8;
    if (this.pressKick < 0.002) this.pressKick = 0;
    this.pressVelocity += (this.pressKick - this.press) * 0.28;
    this.pressVelocity *= 0.6;
    this.press += this.pressVelocity;
    this.render();

    if (
      Math.abs(this.hover - this.hoverTarget) < 0.002 &&
      this.hoverTarget < 0.002 &&
      Math.abs(this.washX - this.targetWashX) < 0.001 &&
      Math.abs(this.washY - this.targetWashY) < 0.001 &&
      this.pressKick === 0 &&
      Math.abs(this.press) < 0.002 &&
      Math.abs(this.pressVelocity) < 0.002
    ) {
      this.pause();
    }
  }

  renderStill() {
    this.resize();
    this.buildSceneNow();
    this.render();
  }

  render() {
    if (
      !this.gl ||
      !this.program ||
      !this.artTexture ||
      !this.fieldTexture
    ) {
      return;
    }
    this.gl.clear(this.gl.COLOR_BUFFER_BIT);
    const angle =
      REST_ANGLE + (this.washX - 0.5) * 1.4 * this.hover;
    this.gl.useProgram(this.program);
    this.gl.activeTexture(this.gl.TEXTURE0);
    this.gl.bindTexture(this.gl.TEXTURE_2D, this.artTexture);
    this.gl.uniform1i(this.locations.uArt, 0);
    this.gl.activeTexture(this.gl.TEXTURE1);
    this.gl.bindTexture(this.gl.TEXTURE_2D, this.fieldTexture);
    this.gl.uniform1i(this.locations.uField, 1);
    this.gl.activeTexture(this.gl.TEXTURE2);
    this.gl.bindTexture(this.gl.TEXTURE_2D, this.weaveTexture);
    this.gl.uniform1i(this.locations.uWeave, 2);
    this.gl.uniform1f(this.locations.uWeaveScale, WEAVE_SCALE);
    this.gl.uniform2f(
      this.locations.uTexel,
      1 / this.textureWidth,
      1 / this.textureHeight,
    );
    this.gl.uniform2f(
      this.locations.uLight,
      Math.cos(angle),
      Math.sin(angle),
    );
    this.gl.uniform1f(this.locations.uLightZ, LIGHT_Z);
    this.gl.uniform2f(
      this.locations.uWash,
      this.washX,
      this.washY,
    );
    this.gl.uniform1f(this.locations.uHover, this.hover);
    this.gl.uniform1f(
      this.locations.uPress,
      Math.max(0, Math.min(1, this.press)),
    );
    this.gl.uniform2f(
      this.locations.uPressPos,
      this.pressX,
      this.pressY,
    );
    this.gl.uniform1f(
      this.locations.uAspect,
      this.width / Math.max(1, this.height),
    );
    this.gl.uniform3f(
      this.locations.uFabric,
      FABRIC[0],
      FABRIC[1],
      FABRIC[2],
    );
    this.gl.uniform1f(this.locations.uDepth, 1.15);
    this.gl.drawArrays(this.gl.TRIANGLE_STRIP, 0, 4);

    if (!this.painted) {
      this.painted = true;
      this.host.dataset.embroideryReady = "true";
      this.canvas.style.opacity = "1";
    }
  }

  destroy() {
    this.destroyed = true;
    if (this.buildScheduled) {
      if (window.cancelIdleCallback) {
        window.cancelIdleCallback(this.buildScheduled);
      } else {
        window.clearTimeout(this.buildScheduled);
      }
      this.buildScheduled = 0;
    }
    this.stop();
    this.host.removeEventListener("pointermove", this.onMove);
    if (this.gl) {
      if (this.artTexture) this.gl.deleteTexture(this.artTexture);
      if (this.fieldTexture) this.gl.deleteTexture(this.fieldTexture);
      if (this.weaveTexture) this.gl.deleteTexture(this.weaveTexture);
      if (this.quad) this.gl.deleteBuffer(this.quad);
      this.gl.getExtension("WEBGL_lose_context")?.loseContext();
    }
    this.canvas.remove();
  }
}

function makeScene(width, height, fontFamily) {
  const makeCanvas = () => {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    return canvas;
  };
  const border = Math.max(2.2, height * 0.012);
  const bevel = Math.max(1.25, height * 0.006);
  const cover = makeCanvas();
  const coverContext = cover.getContext("2d");
  const ink = makeCanvas();
  const inkContext = ink.getContext("2d");
  const ring = makeCanvas();
  const ringContext = ring.getContext("2d");
  const direction = makeCanvas();
  const directionContext = direction.getContext("2d");
  const art = makeCanvas();
  const artContext = art.getContext("2d");

  artContext.fillStyle = rgb(FABRIC);
  artContext.fillRect(0, 0, width, height);
  coverContext.globalCompositeOperation = "lighten";
  inkContext.globalCompositeOperation = "lighten";
  ringContext.globalCompositeOperation = "lighten";

  WORDS.forEach((patch) => {
    const glyph = makeCanvas();
    drawWord(glyph.getContext("2d"), patch, width, height, fontFamily);

    const silhouette = makeCanvas();
    dilate(silhouette.getContext("2d"), glyph, border * 1.85);
    const inner = makeCanvas();
    dilate(inner.getContext("2d"), glyph, border * 0.95);
    const borderBand = makeCanvas();
    const borderContext = borderBand.getContext("2d");
    borderContext.drawImage(silhouette, 0, 0);
    borderContext.globalCompositeOperation = "destination-out";
    borderContext.drawImage(inner, 0, 0);
    borderContext.globalCompositeOperation = "source-over";

    const layer = makeCanvas();
    const layerContext = layer.getContext("2d");
    layerContext.drawImage(silhouette, 0, 0);
    layerContext.globalCompositeOperation = "source-in";
    layerContext.fillStyle = rgb(patch.fill);
    layerContext.fillRect(0, 0, width, height);
    layerContext.globalCompositeOperation = "source-over";
    paintMasked(layerContext, borderBand, patch.border);
    paintMasked(layerContext, glyph, patch.ink);
    artContext.drawImage(layer, 0, 0);

    coverContext.drawImage(silhouette, 0, 0);
    punchThenAdd(inkContext, silhouette, glyph);
    punchThenAdd(ringContext, silhouette, borderBand);
    directionContext.drawImage(glyph, 0, 0);
  });

  const puff = makeCanvas();
  const puffContext = puff.getContext("2d");
  puffContext.filter = `blur(${bevel.toFixed(2)}px)`;
  puffContext.drawImage(cover, 0, 0);
  puffContext.filter = "none";

  const glyphGradient = makeCanvas();
  const glyphGradientContext = glyphGradient.getContext("2d");
  glyphGradientContext.filter =
    `blur(${Math.max(2, height * 0.02).toFixed(2)}px)`;
  glyphGradientContext.drawImage(direction, 0, 0);
  glyphGradientContext.filter = "none";

  const rimGradient = makeCanvas();
  const rimGradientContext = rimGradient.getContext("2d");
  rimGradientContext.filter =
    `blur(${Math.max(2, height * 0.016).toFixed(2)}px)`;
  rimGradientContext.drawImage(cover, 0, 0);
  rimGradientContext.filter = "none";

  const coverageData = puffContext.getImageData(
    0,
    0,
    width,
    height,
  ).data;
  const inkData = inkContext.getImageData(0, 0, width, height).data;
  const ringData = ringContext.getImageData(0, 0, width, height).data;
  const glyphData = glyphGradientContext.getImageData(
    0,
    0,
    width,
    height,
  ).data;
  const rimData = rimGradientContext.getImageData(
    0,
    0,
    width,
    height,
  ).data;
  const field = new Uint8Array(width * height * 4);

  const gradient = (source, x, y) => {
    const at = (sampleX, sampleY) => {
      const safeX = Math.max(0, Math.min(width - 1, sampleX));
      const safeY = Math.max(0, Math.min(height - 1, sampleY));
      return source[(safeY * width + safeX) * 4 + 3];
    };
    return [
      at(x + 1, y) - at(x - 1, y),
      at(x, y + 1) - at(x, y - 1),
    ];
  };

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const index = (y * width + x) * 4;
      const isBorder =
        ringData[index + 3] > 40 && inkData[index + 3] < 40;
      const [dx, dy] = isBorder
        ? gradient(rimData, x, y)
        : gradient(glyphData, x, y);
      let angle = Math.atan2(dy, dx) + Math.PI / 2;
      angle = ((angle % Math.PI) + Math.PI) % Math.PI;
      field[index] = coverageData[index + 3];
      field[index + 1] = inkData[index + 3];
      field[index + 2] = ringData[index + 3];
      field[index + 3] = Math.round((angle / Math.PI) * 255);
    }
  }

  return {
    art,
    field: { data: field, width, height },
  };
}

function rgb(color) {
  const channel = (value) =>
    Math.round(Math.max(0, Math.min(1, value)) * 255);
  return `rgb(${channel(color[0])},${channel(color[1])},${channel(color[2])})`;
}

function paintMasked(context, mask, color) {
  const canvas = document.createElement("canvas");
  canvas.width = context.canvas.width;
  canvas.height = context.canvas.height;
  const masked = canvas.getContext("2d");
  masked.drawImage(mask, 0, 0);
  masked.globalCompositeOperation = "source-in";
  masked.fillStyle = rgb(color);
  masked.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(canvas, 0, 0);
}

function dilate(context, source, radius) {
  const steps = 28;
  for (let scale = 1; scale >= 0.5; scale -= 0.5) {
    for (let index = 0; index < steps; index += 1) {
      const angle = (index / steps) * Math.PI * 2;
      context.drawImage(
        source,
        Math.cos(angle) * radius * scale,
        Math.sin(angle) * radius * scale,
      );
    }
  }
  context.drawImage(source, 0, 0);
}

function punchThenAdd(context, silhouette, addition) {
  context.globalCompositeOperation = "destination-out";
  context.drawImage(silhouette, 0, 0);
  context.globalCompositeOperation = "lighten";
  context.drawImage(addition, 0, 0);
}

function drawWord(context, patch, width, height, fontFamily) {
  const size = patch.scale * height;
  context.save();
  context.translate(patch.cx * width, patch.cy * height);
  context.rotate((patch.rotDeg * Math.PI) / 180);
  context.font = `600 ${size}px ${fontFamily}`;
  context.fillStyle = "#fff";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(patch.word, 0, 0);
  context.restore();
}
