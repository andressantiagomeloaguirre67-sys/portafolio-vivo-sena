/**
 * VORTEX // ADSO PRO — Frontend Architecture & 3D 4-Corner Tri-Color Assembly
 * - Al iniciar el sitio web, 240 cuadros 3D en los 3 colores del robot
 *   (Gris Titanio, Azul Eléctrico y Rojo Carmesí) emergen desde las 4 esquinas
 *   de la pantalla del computador y convergen para materializar al Guardián Aegis.
 * - El robot replica exactamente el diseño de Descargas y mueve EXCLUSIVAMENTE
 *   sus ojos rojos en 3D siguiendo el cursor en tiempo real.
 */

const prefersReducedMotion = window.matchMedia(
  "(prefers-reduced-motion: reduce)"
).matches;

const state = {
  scene: null,
  camera: null,
  renderer: null,
  spiralGroup: null,
  orbitalRingsGroup: null,
  shardMeshes: [],
  shardData: [],
  assemblyProgress: { value: prefersReducedMotion ? 1 : 0 },
  mouseX: 0,
  mouseY: 0,
  targetX: 0,
  targetY: 0,
  eyeLookX: 0,
  eyeLookY: 0,
  eyeTargetX: 0,
  eyeTargetY: 0,
  clock: new THREE.Clock(),
  introTimeline: null,
  dialogIndex: 0,
};

const AEGIS_INSIGHTS = [
  {
    led: "#ff1e38",
    spec: "Titanio · 768-D",
    text: "Analizo la huella semántica de cada propuesta antes de escribir la primera línea, garantizando proyectos únicos en cada ficha.",
  },
  {
    led: "#1e88ff",
    spec: "Sandbox · CSP",
    text: "Cada entrega .zip se ejecuta en vivo dentro de un contenedor aislado para que instructores y aprendices evalúen software real.",
  },
  {
    led: "#30d158",
    spec: "Relevo · Activo",
    text: "Si una consulta involucra diagramas UML o lógica de negocio profunda, la transfiero automáticamente al instructor líder del trimestre.",
  },
];

/* ==========================================================================
   1. ESCENA 3D THREE.JS: CUADROS DE 3 COLORES DESDE LAS 4 ESQUINAS
   ========================================================================== */
function initThreeScene() {
  const canvas = document.getElementById("webgl-canvas");
  if (!canvas) return;

  state.scene = new THREE.Scene();

  state.camera = new THREE.PerspectiveCamera(
    42,
    window.innerWidth / window.innerHeight,
    0.1,
    100
  );
  state.camera.position.set(0, 0.2, prefersReducedMotion ? 8.2 : 12.5);

  state.renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: true,
    powerPreference: "high-performance",
  });
  state.renderer.setSize(window.innerWidth, window.innerHeight);
  state.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  state.renderer.toneMapping = THREE.ACESFilmicToneMapping;
  state.renderer.toneMappingExposure = 1.25;

  // Iluminación de estudio tricolor (Blanco neutro, Azul eléctrico y Rojo carmesí)
  const ambientLight = new THREE.AmbientLight(0xd8dee9, 0.65);
  state.scene.add(ambientLight);

  const studioKeyLight = new THREE.DirectionalLight(0xffffff, 2.6);
  studioKeyLight.position.set(5, 8, 7);
  state.scene.add(studioKeyLight);

  const blueRimLight = new THREE.DirectionalLight(0x1e88ff, 2.2);
  blueRimLight.position.set(-7, 4, -4);
  state.scene.add(blueRimLight);

  const crimsonFillLight = new THREE.PointLight(0xff1e38, 1.9, 25);
  crimsonFillLight.position.set(3.5, 0.8, 5.5);
  state.scene.add(crimsonFillLight);

  buildFourCornerTriColorShards();
  buildPrecisionOrbitalRings();
}

/**
 * Crea 240 cuadros 3D en los 3 colores exactos del robot:
 * 1) Gris Titanio (#7d8594)
 * 2) Azul Eléctrico (#1e88ff)
 * 3) Rojo Carmesí (#ff1e38)
 * que salen desde las 4 esquinas de la pantalla del computador y se unen
 * en la silueta del robot para materializarlo.
 */
/**
 * Calcula en tiempo real la coordenada 3D exacta detrás del muñeco (#aegis-sculpture-frame)
 * sin mover al robot de su lugar en la página, y devuelve también las 4 esquinas de la pantalla.
 */
function getRobotStageProjection() {
  const aegisFrame = document.getElementById("aegis-sculpture-frame");
  const stageEl = document.getElementById("aegis-section");
  const camY = state.camera ? state.camera.position.y : 0.2;
  const camZ = state.camera ? state.camera.position.z : 8.2;
  const fovRad = THREE.MathUtils.degToRad(state.camera ? state.camera.fov * 0.5 : 21);
  const groupZ = -0.35;
  const dist = camZ - groupZ;
  const visH = Math.tan(fovRad) * dist;
  const visW = visH * (window.innerWidth / Math.max(1, window.innerHeight));

  let screenX = window.innerWidth * 0.72;
  let screenY = window.innerHeight * 0.48;

  if (aegisFrame) {
    const rect = aegisFrame.getBoundingClientRect();
    const gsapY = typeof gsap !== "undefined" ? Number(gsap.getProperty(aegisFrame, "y")) || 0 : 0;
    if (rect.width > 0 && rect.height > 0) {
      // El centro del pecho/torso del robot en la imagen recortada está en 48% X, 48% Y
      screenX = rect.left + rect.width * 0.48;
      screenY = rect.top - gsapY + rect.height * 0.48;
    }
  } else if (stageEl) {
    const rect = stageEl.getBoundingClientRect();
    screenX = rect.left + rect.width * 0.5;
    screenY = rect.top + rect.height * 0.45;
  }

  const ndcX = (screenX / Math.max(1, window.innerWidth)) * 2 - 1;
  const ndcY = -(screenY / Math.max(1, window.innerHeight)) * 2 + 1;

  const worldX = ndcX * visW;
  const worldY = camY + ndcY * visH;

  // Las 4 esquinas exactas del monitor en coordenadas locales respecto a (worldX, worldY)
  const corners = [
    new THREE.Vector3(-1.04 * visW - worldX, +1.04 * visH - ndcY * visH, -1.2), // Superior Izquierda
    new THREE.Vector3(+1.04 * visW - worldX, +1.04 * visH - ndcY * visH, -1.2), // Superior Derecha
    new THREE.Vector3(-1.04 * visW - worldX, -1.04 * visH - ndcY * visH, -1.2), // Inferior Izquierda
    new THREE.Vector3(+1.04 * visW - worldX, -1.04 * visH - ndcY * visH, -1.2), // Inferior Derecha
  ];

  return { worldX, worldY, groupZ, corners };
}

/**
 * Crea 620 cuadrados 3D en los 3 colores exactos del robot:
 * 1) Gris Titanio (#8a93a6)
 * 2) Azul Eléctrico (#1e88ff)
 * 3) Rojo Carmesí (#ff1e38)
 * que salen desde las 4 esquinas del computador y se unen exactamente
 * detrás del muñeco para formar su silueta.
 */
function buildFourCornerTriColorShards() {
  state.spiralGroup = new THREE.Group();
  const proj = getRobotStageProjection();
  state.spiralGroup.position.set(proj.worldX, proj.worldY, proj.groupZ);
  state.scene.add(state.spiralGroup);

  // Paleta de 3 colores del robot: Gris Titanio, Azul Eléctrico, Rojo Carmesí
  const palette = [
    // 1. Gris Titanio Metálico (Armadura)
    new THREE.MeshStandardMaterial({
      color: 0x8a93a6,
      metalness: 0.92,
      roughness: 0.16,
    }),
    // 2. Azul Eléctrico Luminoso (Núcleo y Frente)
    new THREE.MeshStandardMaterial({
      color: 0x1e88ff,
      metalness: 0.75,
      roughness: 0.14,
      emissive: 0x0b5ed7,
      emissiveIntensity: 0.85,
    }),
    // 3. Rojo Carmesí Luminoso (Ojos y Reactor Central)
    new THREE.MeshStandardMaterial({
      color: 0xff1e38,
      metalness: 0.75,
      roughness: 0.14,
      emissive: 0xd90429,
      emissiveIntensity: 0.95,
    }),
  ];

  const shardGeo = new THREE.BoxGeometry(0.115, 0.115, 0.024);
  const shardCount = window.innerWidth < 768 ? 340 : 620;

  for (let i = 0; i < shardCount; i++) {
    const mat = palette[i % 3];
    const mesh = new THREE.Mesh(shardGeo, mat);

    // Silueta objetivo del robot centrada en (0,0,0) justo detrás del muñeco
    const t = i / shardCount;
    const yTarget = (t - 0.5) * 3.5;
    const shoulderSpan =
      0.38 +
      0.42 * Math.sin(t * Math.PI * 1.75) +
      (t > 0.52 && t < 0.84 ? 0.48 : 0);
    const angleTarget = i * 2.39996;
    const radiusFactor = 0.25 + 0.75 * ((i * 37 % 100) / 100);
    const xTarget = Math.cos(angleTarget) * shoulderSpan * radiusFactor;
    const zTarget = -0.35 + Math.sin(angleTarget) * 0.28;

    // Halo posterior: una fracción de cuadrados se queda flotando sutilmente detrás del muñeco
    const staysBehindHalo = i % 5 === 0;
    const haloRadius = 1.15 + ((i * 19) % 10) * 0.08;
    const haloX = Math.cos(angleTarget) * haloRadius;
    const haloY = (t - 0.5) * 3.8;
    const haloZ = -0.75 - (i % 4) * 0.12;

    const cornerIdx = i % 4;
    const streamOrder = Math.floor(i / 4) / (shardCount / 4);

    state.shardData.push({
      cornerIdx,
      streamOrder,
      spreadX: ((i * 17) % 13) * 0.11,
      spreadY: ((i * 23) % 13) * 0.09,
      target: new THREE.Vector3(xTarget, yTarget, zTarget),
      haloTarget: new THREE.Vector3(haloX, haloY, haloZ),
      staysBehindHalo,
      delay: streamOrder * 0.34,
      phaseOffset: i * 0.07,
    });

    state.spiralGroup.add(mesh);
    state.shardMeshes.push(mesh);
  }
}

/**
 * Crea dos anillos giroscópicos sutiles en azul y rojo exactamente detrás del muñeco.
 */
function buildPrecisionOrbitalRings() {
  state.orbitalRingsGroup = new THREE.Group();
  const proj = getRobotStageProjection();
  state.orbitalRingsGroup.position.set(proj.worldX, proj.worldY, -0.9);
  state.scene.add(state.orbitalRingsGroup);

  const ringBlueMat = new THREE.MeshBasicMaterial({
    color: 0x1e88ff,
    transparent: true,
    opacity: 0.16,
  });

  const ringRedMat = new THREE.MeshBasicMaterial({
    color: 0xff1e38,
    transparent: true,
    opacity: 0.14,
  });

  const ring1 = new THREE.Mesh(new THREE.TorusGeometry(2.2, 0.004, 16, 128), ringBlueMat);
  ring1.rotation.x = Math.PI * 0.38;
  ring1.rotation.y = Math.PI * 0.12;

  const ring2 = new THREE.Mesh(new THREE.TorusGeometry(2.58, 0.0035, 16, 128), ringRedMat);
  ring2.rotation.x = -Math.PI * 0.32;
  ring2.rotation.y = -Math.PI * 0.18;

  state.orbitalRingsGroup.add(ring1, ring2);
}

/**
 * Interpola los 620 cuadrados 3D de 3 colores desde las 4 esquinas del computador
 * hacia el punto exacto detrás del muñeco donde se unen y emerge el robot.
 */
function updateFourCornerAssembly(p, elapsed) {
  const proj = getRobotStageProjection();
  if (state.spiralGroup) {
    state.spiralGroup.position.set(proj.worldX, proj.worldY, proj.groupZ);
  }
  if (state.orbitalRingsGroup) {
    state.orbitalRingsGroup.position.set(proj.worldX, proj.worldY, -0.9);
  }

  // Cuando el robot emerge (p > 0.72), los cuadrados centrales se funden con su cuerpo
  // mientras el halo trasero permanece flotando suavemente detrás del muñeco
  const coreFadeScale = p > 0.74 ? Math.max(0.001, 1 - (p - 0.74) / 0.26) : 1;
  const behindHaloBlend = p > 0.70 ? Math.min(1, (p - 0.70) / 0.30) : 0;

  for (let i = 0; i < state.shardMeshes.length; i++) {
    const mesh = state.shardMeshes[i];
    const data = state.shardData[i];

    const baseCorner = proj.corners[data.cornerIdx];
    const signX = data.cornerIdx % 2 === 0 ? -1 : 1;
    const signY = data.cornerIdx < 2 ? 1 : -1;

    const startX = baseCorner.x + signX * (data.streamOrder * 3.4 + data.spreadX);
    const startY = baseCorner.y + signY * (data.streamOrder * 2.2 + data.spreadY);
    const startZ = baseCorner.z - data.streamOrder * 2.0;

    // Arco suave desde cada una de las 4 esquinas hacia el centro exacto del robot
    const ctrlX = startX * 0.38;
    const ctrlY = startY * 0.32;
    const ctrlZ = 1.6 + (i % 5) * 0.18;

    const rawP = Math.max(0, Math.min(1, (p - data.delay * (1 - p)) / (1 - data.delay * 0.55)));
    const localP = rawP < 0.5 ? 2 * rawP * rawP : 1 - Math.pow(-2 * rawP + 2, 2) / 2;
    const inv = 1 - localP;

    // Destino final: se unen en la silueta del robot, y los del halo quedan flotando detrás del muñeco
    const endX = data.staysBehindHalo
      ? data.target.x * (1 - behindHaloBlend) + data.haloTarget.x * behindHaloBlend + Math.sin(elapsed * 0.7 + data.phaseOffset) * 0.08 * behindHaloBlend
      : data.target.x;
    const endY = data.staysBehindHalo
      ? data.target.y * (1 - behindHaloBlend) + data.haloTarget.y * behindHaloBlend + Math.cos(elapsed * 0.6 + data.phaseOffset) * 0.08 * behindHaloBlend
      : data.target.y;
    const endZ = data.staysBehindHalo
      ? data.target.z * (1 - behindHaloBlend) + data.haloTarget.z * behindHaloBlend
      : data.target.z;

    const x = inv * inv * startX + 2 * inv * localP * ctrlX + localP * localP * endX;
    const y = inv * inv * startY + 2 * inv * localP * ctrlY + localP * localP * endY;
    const z = inv * inv * startZ + 2 * inv * localP * ctrlZ + localP * localP * endZ;

    mesh.position.set(x, y, z);

    mesh.rotation.x = inv * 2.2 + Math.sin(elapsed * 1.1 + data.phaseOffset) * 0.16;
    mesh.rotation.y = inv * 1.9 + Math.cos(elapsed * 0.9 + data.phaseOffset) * 0.16;
    mesh.rotation.z = inv * 1.5;

    const finalScale = data.staysBehindHalo ? 1 - behindHaloBlend * 0.42 : coreFadeScale;
    mesh.scale.setScalar(finalScale);
  }
}

/* ==========================================================================
   2. REVELADO TIPOGRÁFICO DE PRECISIÓN & ANIMACIÓN DE ENTRADA (GSAP)
   ========================================================================== */
function animateEditorialHeadline(element, duration = 1.15) {
  if (!element) return;
  const finalText = element.getAttribute("data-text") || element.textContent.trim();
  const glyphs = "·—/01";
  const length = finalText.length;
  const proxy = { progress: 0 };

  gsap.to(proxy, {
    progress: 1,
    duration,
    ease: "power3.out",
    onUpdate: () => {
      const lockIndex = Math.floor(proxy.progress * length);
      let output = "";
      for (let i = 0; i < length; i++) {
        const char = finalText[i];
        if (char === " ") {
          output += " ";
        } else if (i <= lockIndex) {
          output += char;
        } else if (i <= lockIndex + 3) {
          output += glyphs[(i + Math.floor(proxy.progress * 24)) % glyphs.length];
        } else {
          output += "";
        }
      }
      element.textContent = output;
    },
    onComplete: () => {
      element.textContent = finalText;
    },
  });
}

function runIntroTimeline() {
  const canvas = document.getElementById("webgl-canvas");
  const navbar = document.getElementById("main-navbar");
  const badge = document.getElementById("assembly-phase-badge");
  const badgeText = document.getElementById("assembly-phase-text");
  const aegisFrame = document.getElementById("aegis-sculpture-frame");
  const heroCopy = document.getElementById("hero-title-rise");
  const titleEl = document.getElementById("scramble-title");
  const subtitleEl = document.getElementById("hero-subtitle");
  const ctaRow = document.getElementById("hero-cta-row");
  const metrics = document.getElementById("precision-metrics");
  const hudCard = document.getElementById("agent-hud-card");
  const bentoCards = document.querySelectorAll(".bento-card");
  const counterEl = document.getElementById("counter-value");

  if (prefersReducedMotion) {
    gsap.set(
      [canvas, navbar, aegisFrame, heroCopy, subtitleEl, ctaRow, metrics, hudCard, ...bentoCards],
      { opacity: 1, clearProps: "transform,filter" }
    );
    if (badge) badge.style.display = "none";
    if (counterEl) counterEl.textContent = "3.2";
    state.assemblyProgress.value = 1;
    updateFourCornerAssembly(1, 0);
    return;
  }

  if (state.introTimeline) state.introTimeline.kill();

  // Estado inicial: cuadros listos en las 4 esquinas del computador
  state.assemblyProgress.value = 0;
  updateFourCornerAssembly(0, 0);
  state.camera.position.set(0, 0.2, 12.5);

  gsap.set(canvas, { opacity: 0, scale: 1.04 });
  gsap.set(navbar, { opacity: 0, y: -20 });
  gsap.set(aegisFrame, {
    opacity: 0,
    scale: 0.88,
    y: 18,
    filter: "blur(16px) brightness(1.85)",
  });
  gsap.set(heroCopy, { opacity: 0, y: 32 });
  gsap.set([subtitleEl, ctaRow, metrics], { opacity: 0, y: 18 });
  gsap.set(hudCard, { opacity: 0, y: 20, scale: 0.96 });
  gsap.set(bentoCards, { opacity: 0, y: 28 });
  gsap.set(badge, { opacity: 1, y: 0, display: "inline-flex" });

  if (badgeText) {
    badgeText.textContent = "Convergiendo núcleos desde los 4 vértices del sistema";
  }

  const counterProxy = { val: 0 };
  const tl = gsap.timeline({ defaults: { ease: "power3.out" } });
  state.introTimeline = tl;

  // 1. Entrada del lienzo 3D y acercamiento pausado de cámara
  tl.to(canvas, { opacity: 1, scale: 1, duration: 1.4 }, 0);
  tl.to(state.camera.position, { z: 8.2, duration: 5.4, ease: "sine.inOut" }, 0);

  // 2. Cuadros grises, azules y rojos saliendo despacio de las 4 esquinas y uniéndose con calma en el centro
  tl.to(
    state.assemblyProgress,
    {
      value: 1,
      duration: 5.2,
      ease: "sine.inOut",
    },
    0.1
  );

  // 3. Al momento de unirse los cuadros (t = 3.85s), emerge suavemente el robot con sus ojos rojos encendidos
  tl.to(
    aegisFrame,
    {
      opacity: 1,
      scale: 1,
      y: 0,
      filter: "blur(0px) brightness(1)",
      duration: 1.85,
      ease: "power3.out",
      onStart: () => {
        if (badgeText) {
          badgeText.textContent = "Aegis Neural Engine · Guardián en línea";
        }
      },
    },
    3.85
  );

  // 4. Elevación editorial del bloque tipográfico
  tl.to(
    heroCopy,
    {
      opacity: 1,
      y: 0,
      duration: 1.2,
      onStart: () => animateEditorialHeadline(titleEl, 1.15),
    },
    1.8
  );

  // 5. Aparición de barra de navegación Apple Glass, subtítulo, botones y píldora VisionOS
  tl.to(navbar, { opacity: 1, y: 0, duration: 1.0 }, 1.2);
  tl.to(subtitleEl, { opacity: 1, y: 0, duration: 1.0 }, 2.2);
  tl.to(ctaRow, { opacity: 1, y: 0, duration: 1.0 }, 2.5);
  tl.to(hudCard, { opacity: 1, y: 0, scale: 1, duration: 1.1 }, 4.2);
  tl.to(metrics, { opacity: 1, y: 0, duration: 1.0 }, 2.8);

  // 6. Contador de precisión (0.0 -> 3.2 ms) y tarjetas Bento
  tl.to(
    counterProxy,
    {
      val: 3.2,
      duration: 1.8,
      onUpdate: () => {
        if (counterEl) counterEl.textContent = counterProxy.val.toFixed(1);
      },
    },
    2.8
  );

  tl.to(
    bentoCards,
    {
      opacity: 1,
      y: 0,
      duration: 1.0,
      stagger: 0.12,
    },
    3.2
  );

  tl.to(
    badge,
    {
      opacity: 0,
      y: 10,
      duration: 0.7,
      onComplete: () => {
        if (badge) badge.style.display = "none";
      },
    },
    5.4
  );
}

/* ==========================================================================
   3. SEGUIMIENTO 3D EXCLUSIVO DE LOS OJOS CON EL CURSOR + CAMBIO DE TEMA
   ========================================================================== */
function syncHomeThemeButton() {
  const current = document.documentElement.getAttribute("data-theme") || "dark";
  const sunIcon = document.getElementById("home-icon-sun");
  const moonIcon = document.getElementById("home-icon-moon");
  const label = document.getElementById("home-theme-label");
  if (current === "light") {
    sunIcon?.classList.add("is-hidden");
    moonIcon?.classList.remove("is-hidden");
    if (label) label.textContent = "Modo Oscuro";
  } else {
    sunIcon?.classList.remove("is-hidden");
    moonIcon?.classList.add("is-hidden");
    if (label) label.textContent = "Modo Claro";
  }
}

function initInteractions() {
  const aegisFrame = document.getElementById("aegis-sculpture-frame");
  const themeBtn = document.getElementById("btn-theme-home");

  syncHomeThemeButton();
  if (themeBtn) {
    themeBtn.addEventListener("click", () => {
      const actual = document.documentElement.getAttribute("data-theme") || "dark";
      const nuevo = actual === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", nuevo);
      localStorage.setItem("vortex_theme", nuevo);
      syncHomeThemeButton();
    });
  }

  window.addEventListener(
    "pointermove",
    (e) => {
      state.targetX = (e.clientX / window.innerWidth) * 2 - 1;
      state.targetY = -(e.clientY / window.innerHeight) * 2 + 1;

      // Calcular dirección exacta del cursor respecto a los ojos del robot
      if (aegisFrame) {
        const rect = aegisFrame.getBoundingClientRect();
        const eyeCenterX = rect.left + rect.width * 0.563;
        const eyeCenterY = rect.top + rect.height * 0.233;

        const dx = (e.clientX - eyeCenterX) / (window.innerWidth * 0.38);
        const dy = (e.clientY - eyeCenterY) / (window.innerHeight * 0.38);

        state.eyeTargetX = Math.max(-1, Math.min(1, dx));
        state.eyeTargetY = Math.max(-1, Math.min(1, dy));
      } else {
        state.eyeTargetX = Math.max(-1, Math.min(1, state.targetX));
        state.eyeTargetY = Math.max(-1, Math.min(1, -state.targetY));
      }
    },
    { passive: true }
  );

  window.addEventListener(
    "resize",
    () => {
      if (!state.camera || !state.renderer) return;
      state.camera.aspect = window.innerWidth / window.innerHeight;
      state.camera.updateProjectionMatrix();
      state.renderer.setSize(window.innerWidth, window.innerHeight);
      state.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

      const stageProj = getRobotStageProjection();
      if (state.spiralGroup) state.spiralGroup.position.set(stageProj.worldX, stageProj.worldY, -0.35);
      if (state.orbitalRingsGroup) state.orbitalRingsGroup.position.set(stageProj.worldX, stageProj.worldY, -0.5);
    },
    { passive: true }
  );

  const replayBtn = document.getElementById("btn-replay-intro");
  if (replayBtn) {
    replayBtn.addEventListener("click", () => {
      window.scrollTo({ top: 0, behavior: "smooth" });
      runIntroTimeline();
    });
  }

  if (aegisFrame) {
    aegisFrame.addEventListener("click", () => {
      state.dialogIndex = (state.dialogIndex + 1) % AEGIS_INSIGHTS.length;
      const item = AEGIS_INSIGHTS[state.dialogIndex];
      const speechEl = document.getElementById("agent-speech-text");
      const ledEl = document.getElementById("vision-status-led");
      const specEl = document.querySelector(".vision-pill-spec");

      if (ledEl) {
        ledEl.style.background = item.led;
        ledEl.style.boxShadow = `0 0 12px ${item.led}`;
      }
      if (specEl) specEl.textContent = item.spec;
      if (speechEl) {
        gsap.fromTo(
          speechEl,
          { opacity: 0, y: 5 },
          {
            opacity: 1,
            y: 0,
            duration: 0.35,
            onStart: () => {
              speechEl.textContent = item.text;
            },
          }
        );
      }
    });
  }
}

function animateLoop() {
  requestAnimationFrame(animateLoop);
  if (!state.renderer || !state.scene || !state.camera) return;

  const elapsed = state.clock.getElapsedTime();
  const p = state.assemblyProgress.value;

  state.mouseX += (state.targetX - state.mouseX) * 0.06;
  state.mouseY += (state.targetY - state.mouseY) * 0.06;

  // Interpolación suave para el movimiento exclusivo de los ojos
  state.eyeLookX += (state.eyeTargetX - state.eyeLookX) * 0.14;
  state.eyeLookY += (state.eyeTargetY - state.eyeLookY) * 0.14;

  updateFourCornerAssembly(p, elapsed);

  if (state.orbitalRingsGroup) {
    state.orbitalRingsGroup.rotation.z = elapsed * 0.08;
    state.orbitalRingsGroup.rotation.y = state.mouseX * 0.18;
    state.orbitalRingsGroup.rotation.x = -state.mouseY * 0.14;
  }

  // Mover EXCLUSIVAMENTE los ojos rojos en 3D dentro de sus cuencas siguiendo al cursor
  const eyeLeft = document.getElementById("aegis-eye-left");
  const eyeRight = document.getElementById("aegis-eye-right");
  if (eyeLeft && eyeRight) {
    const maxOffsetX = 3.8; // px dentro de la cuenca ocular
    const maxOffsetY = 3.0; // px dentro de la cuenca ocular
    const ex = state.eyeLookX * maxOffsetX;
    const ey = state.eyeLookY * maxOffsetY;
    const eyeTransform = `translate3d(${ex.toFixed(2)}px, ${ey.toFixed(2)}px, 4px)`;
    eyeLeft.style.transform = eyeTransform;
    eyeRight.style.transform = eyeTransform;
  }

  state.renderer.render(state.scene, state.camera);
}

window.addEventListener("load", () => {
  initThreeScene();
  initInteractions();
  runIntroTimeline();
  animateLoop();
});
