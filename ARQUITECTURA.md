# Arquitectura Definitiva: Portafolio Vivo SENA ADSO (v2.0)

Este documento consolida la arquitectura técnica final incorporando todas las reglas de negocio reales del SENA ADSO: trabajo por **Grupos Scrum**, **1 solo proyecto por grupo**, **alojamiento único de la entrega más reciente**, **rotación trimestral de instructores** y un **Agente IA Guardián de Originalidad** que escala las dudas técnicas y de diagramas directamente al instructor asignado.

---

## 1. Stack Tecnológico Completo

| Capa | Lenguaje / Tecnología | Versión | Propósito en el Proyecto |
| :--- | :--- | :--- | :--- |
| **Backend API** | **Python** + **Django** + **Django REST Framework** | Python 3.12 / Django 5.1 | Monolito modular en 5 apps (`usuarios`, `fichas`, `proyectos`, `revisiones`, `asistente`). |
| **Autenticación** | **SimpleJWT** (`djangorestframework-simplejwt`) | 5.3+ | Inicio de sesión mediante **Documento de Identidad (`documento`)** y contraseña. |
| **Base de Datos + Vectores** | **PostgreSQL** + **`pgvector`** + **`pg_trgm`** | Postgres 16 | Guarda las tablas relacionales, el historial de comentarios y los vectores semánticos para detectar proyectos o nombres repetidos. |
| **Colas Asíncronas** | **Celery** + **Redis** | Celery 5.4 / Redis 7 | Procesa las cargas masivas de Excel/CSV (aprendices y grupos Scrum), envía correos por Gmail SMTP y valida/reemplaza el archivo `.zip` del proyecto. |
| **Almacenamiento** | **MinIO** (S3 Compatible) | Última estable | Aloja únicamente la **versión más reciente** de cada proyecto (reemplazando la anterior para ahorrar espacio). |
| **Agente IA** | **LangGraph** + **Google Gemini API** | `gemini-2.5-flash` + `text-embedding-004` | **Única misión de IA:** Ayudar a buscar/definir la idea del proyecto garantizando que no se repita ni nombre ni idea en el SENA. Si el aprendiz consulta sobre diagramas o lógica del proyecto, le envía la solicitud directo al instructor asignado. |
| **Frontend** | **TypeScript** + **React (Vite)** + **Tailwind CSS** | React 19 | Interfaz rápida y adaptable a celular con Feed vivo (`iframe` bajo demanda) y panel del instructor. |
| **Sandbox de Ejecución** | **Nginx** (Dominio/Puerto aislado) | 1.27 Alpine | Sirve los proyectos estáticos (`HTML/CSS/JS` o compilados `React/Vue`) con `CSP` estricta sin acceso a cookies ni sesión de la plataforma. |

---

## 2. Los 5 Módulos del Backend (`Feed` unido con `Proyectos`)

Se unifican `Feed` y `Proyectos` en un solo módulo de backend (`apps/proyectos`) y se consolidan las entidades:

```text
Portafolio vivo SENA/
├── ARQUITECTURA.md                 # Este documento maestro de arquitectura
├── docker-compose.yml              # Postgres (pgvector), Redis, MinIO, Nginx Sandbox, API, Celery
├── nginx/sandbox.conf              # Configuración de dominio aislado para los iframes
├── backend/
│   ├── config/                     # Settings, Celery, JWT, OpenAPI (Swagger)
│   └── apps/
│       ├── 1. usuarios/            # Login por Documento, activación por Gmail, suspensión con motivo
│       ├── 2. fichas/              # Fichas, Asignación trimestral de instructor, Grupos Scrum, Carga CSV/Excel
│       ├── 3. proyectos/           # Proyecto (1 por Grupo Scrum), Feed paginado, reemplazo de ZIP, Historial
│       ├── 4. revisiones/          # Hilo de Comentarios (Instructor <-> Respuesta Grupo), Consultas escaladas, Reportes
│       └── 5. asistente/           # LangGraph + pgvector (Buscador/Validador de ideas sin repetir y escalado al profe)
└── frontend/
    └── src/features/
        ├── auth/                   # Login con Documento, activar cuenta, recuperar clave
        ├── feed/                   # Vista de tarjetas + botón "Ejecutar" (iframe aislado)
        ├── grupo-proyecto/         # Panel del Grupo Scrum: definir idea con IA, subir último ZIP, ver bitácora
        └── instructor/             # Subir Excel de fichas/grupos, ver alertas de duplicados, comentar y responder dudas
```

---

## 3. Reglas de Negocio Inquebrantables (Cerradas)

### Regla 1: Cuentas, Login por Documento y Prohibición de Eliminar Aprendices
1. **Creación por Excel/CSV:** El instructor crea la ficha y sube el archivo con `nombre_completo`, `documento`, `correo` y `grupo_scrum`.
2. **Invitación por Gmail:** El sistema envía el correo de activación. El aprendiz entra al enlace, su **usuario de login es su `documento`**, crea su contraseña y empieza.
3. **Prohibido eliminar aprendices (`No Delete`):** Un aprendiz **jamás se borra** de la base de datos. Si deserta o tiene un inconveniente, el instructor lo pasa a estado **`SUSPENDIDO / INACTIVO`** y está obligado a registrar un **comentario con el motivo de la suspensión** (`motivo_suspension`).
4. **Efecto en el panel:** Al estar suspendido/inactivo, no puede iniciar sesión y **no aparece** en las alertas de "aprendices sin proyecto".

### Regla 2: Rotación de Instructor por Trimestre
1. **Un instructor -> Muchas fichas:** Un instructor puede tener asignadas múltiples fichas al mismo tiempo porque la carga académica es alta.
2. **Una ficha -> UN SOLO instructor activo:** Una ficha puede cambiar de instructor cada trimestre según lo definan los directivos, pero en PostgreSQL solo puede haber **1 instructor con `activa = True` por ficha** al mismo tiempo.
3. Cuando cambia el trimestre, se desactiva la asignación del instructor anterior (conservando su historial de comentarios) y queda activo el nuevo instructor.

### Regla 3: Grupos Scrum y Proyectos (Relación Estricta)
1. **Creación de Grupos por Carga Masiva:** En el archivo de carga se definen los Grupos Scrum de la ficha.
2. **Mínimo 2 aprendices por Grupo Scrum:** Ningún grupo puede tener menos de 2 aprendices activos.
3. **1 Aprendiz = Máximo 1 Grupo Scrum:** Ningún aprendiz puede estar en más de un grupo.
   - Si en el archivo se repite un `documento` o un **`nombre_completo`** en dos grupos distintos, el sistema **dispara una alerta inmediata** indicando qué persona o personas están repetidas en varios grupos.
4. **1 Grupo Scrum = 1 Solo Proyecto:** Si en una ficha se conforman 5 Grupos Scrum, en esa ficha **solo existirán exactamente 5 proyectos** (uno por grupo).
5. **Separación de un grupo:** Si un grupo se separa o disuelve, el grupo sí se puede eliminar/disolver para reasignar a los aprendices activos, pero los aprendices nunca se eliminan.

### Regla 4: Permisos del Grupo, Alojamiento de 1 Sola Versión y Bitácora
1. **Igualdad en el equipo:** Cualquiera de los aprendices activos del Grupo Scrum puede subir/actualizar el proyecto o retirarlo/eliminarlo.
2. **Constancia tipo "Historia" (`HistorialProyecto`):** Cada acción que haga cualquier miembro del grupo (crear proyecto, actualizar el código, eliminar el proyecto, responder un comentario) queda grabada en una bitácora con **nombre del aprendiz, documento, acción, fecha y hora exacta**.
3. **1 Solo Archivo Alojado (Cero acumular versiones en disco):**
   - Por espacio en el servidor, **solo se aloja la entrega más reciente**.
   - Cuando alguien del grupo sube el nuevo `.zip`, el sistema valida que funcione, **borra el archivo anterior de MinIO/S3** y deja alojado únicamente el código más reciente.
4. **Hilo de Comentarios y Respuestas (Sin guardar repositorios viejos):**
   - El historial que sí se conserva completo en PostgreSQL es el de **los comentarios del instructor y las respuestas del grupo**.
   - Ejemplo: El instructor comenta *"Falta validar el formulario de contacto"*. El grupo sube el código nuevo corrigiendo eso y responde en ese mismo comentario: *"Gracias profe, ya se corrigió en esta subida"*.

### Regla 5: El Agente IA (Guardián de Ideas Únicas + Escalado al Instructor)
1. **Búsqueda y Validación de Idea (Cero Proyectos Repetidos):**
   - El agente ayuda al Grupo Scrum a definir su idea de proyecto y verifica contra PostgreSQL (`pgvector` + similitud de nombres) que **no se repita ni el nombre ni la idea** con ningún otro proyecto del SENA.
   - Si detecta que otro grupo ya tiene esa idea o un nombre similar, les avisa de inmediato y los guía para enfocar la idea hacia algo original.
2. **Escalado Directo al Instructor para Lógica / Diagramas / Código:**
   - Si el aprendiz le pide ayuda con diagramas, validación de lógica o qué le falta al proyecto, como el aprendiz puede redactar mal el prompt y confundir a la IA, **el agente NO inventa correcciones ni hace diagramas**.
   - En su lugar, **envía automáticamente la consulta/solicitud al Instructor activo asignado a su ficha** para que el instructor real revise la lógica con ellos desde su panel.

---

## 4. Diseño Definitivo de Tablas en PostgreSQL (`models.py`)

```python
# ==========================================
# 1. MÓDULO USUARIOS (apps/usuarios/models.py)
# ==========================================
import uuid
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

class RolUsuario(models.TextChoices):
    ADMIN = "ADMIN", "Administrador"
    INSTRUCTOR = "INSTRUCTOR", "Instructor"
    APRENDIZ = "APRENDIZ", "Aprendiz"

class EstadoCuenta(models.TextChoices):
    PENDIENTE = "PENDIENTE", "Pendiente de activación"
    ACTIVO = "ACTIVO", "Activo"
    SUSPENDIDO = "SUSPENDIDO", "Suspendido / Inactivo"

class Usuario(AbstractBaseUser, PermissionsMixin):
    """
    El Aprendiz inicia sesión con su DOCUMENTO.
    PROHIBIDO eliminar aprendices: solo se pasan a SUSPENDIDO dejando motivo.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    documento = models.CharField(max_length=30, unique=True, db_index=True)
    nombre_completo = models.CharField(max_length=180, db_index=True)
    correo = models.EmailField(unique=True, db_index=True)
    rol = models.CharField(max_length=15, choices=RolUsuario.choices)

    estado_cuenta = models.CharField(
        max_length=15, choices=EstadoCuenta.choices, default=EstadoCuenta.PENDIENTE
    )
    is_active = models.BooleanField(default=False)  # True cuando activa cuenta y no está suspendido

    # Auditoría de suspensión (Obligatorio cuando se inactiva/suspende un aprendiz)
    motivo_suspension = models.TextField(blank=True)
    fecha_suspension = models.DateTimeField(null=True, blank=True)
    suspendido_por = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="aprendices_suspendidos"
    )

    acepto_habeas_data = models.BooleanField(default=False)
    creado_en = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "documento"
    REQUIRED_FIELDS = ["nombre_completo", "correo", "rol"]
```

```python
# ==========================================
# 2. MÓDULO FICHAS Y GRUPOS SCRUM (apps/fichas/models.py)
# ==========================================
import uuid
from django.db import models
from django.db.models import Q
from django.conf import settings

class Ficha(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    numero = models.CharField(max_length=20, unique=True, db_index=True)
    programa = models.CharField(max_length=150, default="Análisis y Desarrollo de Software (ADSO)")
    jornada = models.CharField(max_length=20)
    activa = models.BooleanField(default=True)
    creada_en = models.DateTimeField(auto_now_add=True)

class AsignacionInstructor(models.Model):
    """
    - Un instructor puede tener MUCHAS fichas activas.
    - Una ficha SOLO puede tener UN instructor activo por trimestre.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ficha = models.ForeignKey(Ficha, on_delete=models.CASCADE, related_name="asignaciones")
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="fichas_asignadas",
        limit_choices_to={"rol": "INSTRUCTOR"},
    )
    trimestre = models.CharField(max_length=30, help_text="Ej: 2026-Trimestre-3")
    activa = models.BooleanField(default=True, db_index=True)
    fecha_inicio = models.DateTimeField(auto_now_add=True)
    fecha_fin = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["ficha"],
                condition=Q(activa=True),
                name="uq_un_solo_instructor_activo_por_ficha",
            )
        ]

class Matricula(models.Model):
    """Relaciona al aprendiz con su ficha."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    aprendiz = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,  # Prohibido borrar aprendices
        related_name="matriculas",
        limit_choices_to={"rol": "APRENDIZ"},
    )
    ficha = models.ForeignKey(Ficha, on_delete=models.PROTECT, related_name="matriculas")
    activa = models.BooleanField(default=True)
    fecha_matricula = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["aprendiz"],
                condition=Q(activa=True),
                name="uq_una_matricula_activa_por_aprendiz",
            )
        ]

class GrupoScrum(models.Model):
    """
    Grupo Scrum dentro de una ficha.
    - Mínimo 2 aprendices (validado en servicio/carga masiva).
    - Si el grupo se separa, el grupo SÍ se puede eliminar.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ficha = models.ForeignKey(Ficha, on_delete=models.CASCADE, related_name="grupos_scrum")
    nombre_grupo = models.CharField(max_length=100, help_text="Ej: Grupo Scrum 1")
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["ficha", "nombre_grupo"], name="uq_nombre_grupo_por_ficha")
        ]

class MiembroGrupoScrum(models.Model):
    """
    Une a cada aprendiz con su Grupo Scrum.
    - Ningún aprendiz puede estar en más de 1 grupo.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    grupo = models.ForeignKey(GrupoScrum, on_delete=models.CASCADE, related_name="miembros")
    aprendiz = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="miembro_grupo_scrum",
        limit_choices_to={"rol": "APRENDIZ"},
    )
    fecha_ingreso = models.DateTimeField(auto_now_add=True)

class CargaMasiva(models.Model):
    """
    Registra el Excel/CSV de aprendices y grupos, guardando alertas si un nombre
    completo o documento aparece repetido en varios grupos.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instructor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    ficha = models.ForeignKey(Ficha, on_delete=models.CASCADE, related_name="cargas")
    archivo = models.CharField(max_length=500)
    estado = models.CharField(max_length=25, default="PENDIENTE")
    alertas_duplicados = models.JSONField(default=list)  # Personas repetidas en varios grupos o grupos < 2
    creado_en = models.DateTimeField(auto_now_add=True)
```

```python
# ==========================================
# 3. MÓDULO PROYECTOS Y FEED (apps/proyectos/models.py)
# ==========================================
import uuid
from django.db import models
from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from pgvector.django import VectorField
from apps.fichas.models import Ficha, GrupoScrum

class Proyecto(models.Model):
    """
    - Relación 1 a 1 con GrupoScrum (5 grupos = máximo 5 proyectos).
    - Solo aloja 1 archivo (el más reciente) en ruta_codigo_actual.
    - Incluye vector semántico para que ningún proyecto repita idea en el SENA.
    """
    class EstadoProyecto(models.TextChoices):
        DEFINIENDO_IDEA = "DEFINIENDO_IDEA", "Definiendo idea con Agente"
        IDEA_APROBADA = "IDEA_APROBADA", "Idea única aprobada (Sin código aún)"
        PUBLICADO = "PUBLICADO", "Publicado en el Feed"
        ELIMINADO_POR_GRUPO = "ELIMINADO_POR_GRUPO", "Retirado por el grupo"
        RETIRADO_INSTRUCTOR = "RETIRADO_INSTRUCTOR", "Retirado por el instructor"

    class Visibilidad(models.TextChoices):
        FICHA = "FICHA", "Solo la ficha"
        PUBLICO = "PUBLICO", "Público"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ficha = models.ForeignKey(Ficha, on_delete=models.PROTECT, related_name="proyectos")
    grupo_scrum = models.OneToOneField(
        GrupoScrum, on_delete=models.CASCADE, related_name="proyecto"
    )

    # Identidad única del proyecto (Ningún proyecto puede repetir título ni idea)
    titulo = models.CharField(max_length=150, unique=True, db_index=True)
    introduccion = models.TextField()
    embedding_idea = VectorField(dimensions=768, null=True, blank=True)  # Compara que no se repita la idea
    tecnologias = ArrayField(models.CharField(max_length=40), default=list)

    # Alojamiento ÚNICO de la versión más reciente (reemplaza la anterior en MinIO/S3)
    ruta_codigo_actual = models.CharField(max_length=500, blank=True)
    punto_entrada = models.CharField(max_length=255, default="index.html")
    numero_entrega_actual = models.PositiveIntegerField(default=0)
    estado_procesamiento_zip = models.CharField(max_length=20, default="SIN_SUBIR")
    ultimo_error_zip = models.TextField(blank=True)

    estado = models.CharField(
        max_length=25, choices=EstadoProyecto.choices, default=EstadoProyecto.DEFINIENDO_IDEA
    )
    visibilidad = models.CharField(
        max_length=15, choices=Visibilidad.choices, default=Visibilidad.FICHA
    )
    actualizado_en = models.DateTimeField(auto_now=True)

class HistorialProyecto(models.Model):
    """
    Bitácora inmutable ('Historias'): deja constancia de QUIÉN del grupo
    subió el proyecto, actualizó el código o lo eliminó, con fecha y hora exacta.
    """
    class TipoAccion(models.TextChoices):
        REGISTRO_IDEA = "REGISTRO_IDEA", "Registró la idea del proyecto"
        SUBIO_CODIGO = "SUBIO_CODIGO", "Subió / Reemplazó el código del proyecto"
        ELIMINO_PROYECTO = "ELIMINO_PROYECTO", "Eliminó / Retiró el proyecto"
        CAMBIO_ESTADO = "CAMBIO_ESTADO", "Cambió estado o visibilidad"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    proyecto = models.ForeignKey(Proyecto, on_delete=models.CASCADE, related_name="historial")
    realizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    accion = models.CharField(max_length=25, choices=TipoAccion.choices)
    numero_entrega = models.PositiveIntegerField(default=0)
    descripcion_cambio = models.TextField(help_text="Nota de qué cambió o por qué se retiró")
    fecha_hora = models.DateTimeField(auto_now_add=True, db_index=True)
```

```python
# ==========================================
# 4. MÓDULO REVISIONES Y ASISTENTE (apps/revisiones/ y apps/asistente/)
# ==========================================
import uuid
from django.db import models
from django.conf import settings
from apps.proyectos.models import Proyecto

class ComentarioRevision(models.Model):
    """
    Mantiene el historial de comentarios del instructor y las respuestas del Grupo Scrum
    ('Sí profe, gracias, ya se corrigió y se subió el nuevo código'), sin guardar código viejo.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    proyecto = models.ForeignKey(Proyecto, on_delete=models.CASCADE, related_name="comentarios")
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="comentarios_realizados"
    )
    numero_entrega_revisada = models.PositiveIntegerField(default=1)
    comentario_instructor = models.TextField()
    fecha_comentario = models.DateTimeField(auto_now_add=True)

    # Respuesta del Grupo Scrum cuando corrigen y suben el nuevo archivo
    respuesta_grupo = models.TextField(blank=True)
    respondido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="respuestas_comentarios",
    )
    fecha_respuesta = models.DateTimeField(null=True, blank=True)
    corregido_en_entrega = models.PositiveIntegerField(null=True, blank=True)

class ConsultaEscaladaInstructor(models.Model):
    """
    Cuando el aprendiz le pregunta al Agente por diagramas, lógica o qué le falta a su proyecto,
    el Agente NO inventa respuestas (por si el prompt del aprendiz está mal planteado) y le envía
    esta solicitud directamente al Instructor activo de la ficha.
    """
    class EstadoConsulta(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente por revisar el instructor"
        ATENDIDA = "ATENDIDA", "Atendida por el instructor"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    proyecto = models.ForeignKey(Proyecto, on_delete=models.CASCADE, related_name="consultas_escaladas")
    aprendiz = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    instructor_destino = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="consultas_recibidas"
    )
    mensaje_original_aprendiz = models.TextField()
    motivo_escalado = models.CharField(max_length=120, default="Revisión de lógica / diagramas / alcance")
    respuesta_instructor = models.TextField(blank=True)
    estado = models.CharField(max_length=15, choices=EstadoConsulta.choices, default=EstadoConsulta.PENDIENTE)
    creado_en = models.DateTimeField(auto_now_add=True)
    respondido_en = models.DateTimeField(null=True, blank=True)
```
