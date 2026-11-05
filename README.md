# Vortex — Portafolio Vivo SENA (ADSO Pro)

Plataforma académica e institucional para la gestión, auditoría semántica con Inteligencia Artificial (**Aegis Neural Engine**) y ejecución aislada en vivo (**Sandbox CSP**) de proyectos formativos del programa **Análisis y Desarrollo de Software (ADSO)** del SENA.

---

## Características Principales

- **Home Interactivo 3D (`/`)**: Escenario WebGL (Three.js + GLTFLoader + Post-procesado) con el modelo articulado de 38 huesos de **Aegis** (`/assets/robot.glb`), seguimiento ocular/corporal al cursor, iluminación de estudio y estética editorial estilo Apple Pro.
- **Plataforma Unificada (`/app/`) con Modo Oscuro OLED y Modo Blanco (Light Mode)**:
  - **Vista de Aprendiz (`APRENDIZ`)**: Gestión del proyecto del Grupo Scrum, auditoría de originalidad con Aegis IA, despliegue de entregas `.zip` o `index.html` (regla de 1 sola versión activa alojada), atención a observaciones docentes y bitácora inmutable (`HistorialProyecto`).
  - **Vista de Instructor (`INSTRUCTOR`)**: Supervisión de fichas asignadas, conformación masiva de Grupos Scrum vía `.csv`/`.xlsx` con detector de aprendices duplicados, bandeja de consultas escaladas por Aegis IA y directorio de aprendices bajo la **Regla Inquebrantable No-Delete**.
  - **Vista de Coordinación Académica (`ADMIN`)**: Gobernanza global del centro, rotación trimestral de instructores líderes por ficha conservando historial y apertura de nuevas cohortes.
  - **Vitrina Pública y Sandbox CSP**: Ejecución interactiva de proyectos en `iframe` aislado y foro de evaluación por versión.

---

## Estructura del Repositorio

```text
├── ARQUITECTURA.md          # Especificación técnica y reglas de negocio SENA
├── backend/                 # API REST en Django 5 + Django REST Framework + PostgreSQL
│   ├── apps/
│   │   ├── usuarios/        # Autenticación por documento + Regla No-Delete
│   │   ├── fichas/          # Fichas, rotación trimestral y Grupos Scrum
│   │   ├── proyectos/       # Proyectos, bitácora inmutable y Sandbox
│   │   ├── revisiones/      # Evaluación continua y consultas escaladas
│   │   └── asistente/       # Motor semántico Aegis IA
│   └── config/              # Configuración Django, rutas y servidor de medios
├── frontend/
│   ├── meta1d-hero/         # Landing 3D interactiva (Three.js + GLB articulado)
│   └── index.html           # Aplicación SPA con vistas por rol y Modo Blanco/Oscuro
├── nginx/                   # Configuración de aislamiento CSP para el Sandbox
└── docker-compose.yml       # Orquestación de servicios
```

---

## Ejecución Local

1. **Configurar variables de entorno:**
   ```bash
   cp .env.example .env
   ```
2. **Iniciar el servidor backend y frontend unificado (Django):**
   ```bash
   cd backend
   ./.venv/bin/python manage.py migrate
   ./.venv/bin/python manage.py runserver 0.0.0.0:8000
   ```
3. **Accesos en el navegador:**
   - **Home 3D:** `http://localhost:8000/`
   - **Plataforma Académica (`/app/`):** `http://localhost:8000/app/`
   - **Documentación OpenAPI / Swagger:** `http://localhost:8000/api/docs/`
