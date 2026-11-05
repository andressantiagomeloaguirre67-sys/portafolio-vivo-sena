"""
Servicios de negocio del Módulo 3: Proyectos y Sandbox (apps/proyectos/services.py)
Regla 4.3:
- Alojamiento único de la versión más reciente (Cero acumular versiones en disco/MinIO).
- Validación previa atómica del paquete .zip antes de borrar y reemplazar la entrega anterior.
"""

import io
import shutil
import tempfile
import zipfile
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError

from .models import Proyecto

SANDBOX_ROOT = Path(settings.BASE_DIR) / "media" / "sandbox_projects"
MAX_ZIP_UNCOMPRESSED_BYTES = 50 * 1024 * 1024  # 50 MB máximo descomprimido
MAX_ZIP_FILES = 500
EXTENSIONES_EJECUTABLES_PROHIBIDAS = {
    ".php",
    ".phtml",
    ".py",
    ".pyc",
    ".sh",
    ".bash",
    ".exe",
    ".bat",
    ".cmd",
    ".dll",
    ".so",
    ".jsp",
    ".asp",
    ".aspx",
    ".cgi",
}


def limpiar_almacenamiento_proyecto(proyecto: Proyecto) -> None:
    """
    Elimina por completo los archivos alojados de la versión actual del proyecto
    para liberar espacio en el servidor.
    """
    destino_proyecto = SANDBOX_ROOT / str(proyecto.id)
    if destino_proyecto.exists():
        shutil.rmtree(destino_proyecto)


def _desempaquetar_directorio_unico_raiz(carpeta_staging: Path, punto_entrada: str) -> None:
    """
    Si el aprendiz comprimió una carpeta raíz (ej. `mi_proyecto/index.html`) en lugar
    de los archivos en la raíz del .zip, mueve el contenido de esa carpeta al nivel raíz
    del proyecto automáticamente para que `index.html` funcione sin dar error 404.
    """
    if (carpeta_staging / punto_entrada).is_file():
        return

    elementos = [
        p for p in carpeta_staging.iterdir() if p.name not in ("__MACOSX", ".DS_Store")
    ]
    if len(elementos) == 1 and elementos[0].is_dir():
        subcarpeta = elementos[0]
        if (subcarpeta / punto_entrada).is_file():
            for item in list(subcarpeta.iterdir()):
                shutil.move(str(item), str(carpeta_staging / item.name))
            shutil.rmtree(subcarpeta, ignore_errors=True)


def validar_y_reemplazar_entrega_unica(
    proyecto: Proyecto,
    archivo_zip=None,
    codigo_html: str | None = None,
    punto_entrada: str = "index.html",
) -> str:
    """
    Regla 4.3:
    1. Valida primero la nueva entrega en un directorio temporal (integridad del ZIP,
       límites anti-ZipBomb, bloqueo de scripts ejecutables de servidor, prevención de Zip Slip
       y existencia del archivo `punto_entrada`).
    2. Si falla la validación, registra `ultimo_error_zip` en el proyecto y conserva intacta
       la versión anterior.
    3. Si la validación es exitosa, borra por completo la versión anterior en disco y aloja
       únicamente la entrega más reciente.
    """
    SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
    punto_entrada_limpio = (punto_entrada or "index.html").strip().lstrip("/")
    if ".." in Path(punto_entrada_limpio).parts:
        raise ValidationError("El punto de entrada especificado no es válido.")

    staging_dir = Path(tempfile.mkdtemp(prefix=f"sena_proy_{proyecto.id}_"))

    try:
        if archivo_zip:
            contenido = archivo_zip.read()
            if not contenido:
                raise ValidationError("El archivo .zip subido está vacío.")

            try:
                zf_test = zipfile.ZipFile(io.BytesIO(contenido))
            except zipfile.BadZipFile:
                raise ValidationError(
                    "El archivo subido no es un archivo .zip válido o está corrupto."
                )

            with zf_test as zf:
                miembros = [m for m in zf.infolist() if not m.is_dir()]
                if not miembros:
                    raise ValidationError("El archivo .zip no contiene ningún archivo.")
                if len(miembros) > MAX_ZIP_FILES:
                    raise ValidationError(
                        f"El archivo .zip excede el límite máximo de {MAX_ZIP_FILES} archivos."
                    )

                total_bytes = sum(m.file_size for m in miembros)
                if total_bytes > MAX_ZIP_UNCOMPRESSED_BYTES:
                    raise ValidationError(
                        "El tamaño descomprimido del .zip supera el límite permitido de 50 MB."
                    )

                for member in miembros:
                    ruta_rel = Path(member.filename)
                    # Ignorar metadatos de macOS
                    if "__MACOSX" in ruta_rel.parts or ruta_rel.name == ".DS_Store":
                        continue
                    # Prevenir Zip Slip (Path Traversal)
                    if ".." in ruta_rel.parts or ruta_rel.is_absolute():
                        raise ValidationError(
                            f"Ruta insegura detectada dentro del .zip: '{member.filename}'."
                        )
                    ext = ruta_rel.suffix.lower()
                    if ext in EXTENSIONES_EJECUTABLES_PROHIBIDAS:
                        raise ValidationError(
                            f"Por seguridad del Sandbox, no se permiten archivos ejecutables de servidor ('{ruta_rel.name}')."
                        )

                    destino_archivo = (staging_dir / ruta_rel).resolve()
                    if not str(destino_archivo).startswith(str(staging_dir.resolve())):
                        raise ValidationError("Intento de escritura fuera del Sandbox detectado.")

                    destino_archivo.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as origen, open(destino_archivo, "wb") as salida:
                        shutil.copyfileobj(origen, salida)

            _desempaquetar_directorio_unico_raiz(staging_dir, punto_entrada_limpio)

            archivo_entrada = (staging_dir / punto_entrada_limpio).resolve()
            if (
                not str(archivo_entrada).startswith(str(staging_dir.resolve()))
                or not archivo_entrada.is_file()
            ):
                raise ValidationError(
                    f"No se encontró el archivo de entrada '{punto_entrada_limpio}' dentro del paquete .zip."
                )
        else:
            html_final = codigo_html or f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <title>{proyecto.titulo}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 0; padding: 24px; background: #0f172a; color: #f8fafc; }}
    .card {{ max-width: 680px; margin: 0 auto; background: #1e293b; border: 1px solid #334155; border-radius: 14px; padding: 24px; }}
    .badge {{ display: inline-block; background: #16a34a; color: white; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; }}
    button {{ background: #38bdf8; color: #0f172a; border: none; padding: 10px 16px; border-radius: 8px; font-weight: 700; cursor: pointer; margin-top: 12px; }}
  </style>
</head>
<body>
  <div class="card">
    <span class="badge">Entrega #{proyecto.numero_entrega_actual + 1} · Sandbox Aislado SENA</span>
    <h1>{proyecto.titulo}</h1>
    <p>{proyecto.introduccion}</p>
    <button onclick="document.getElementById('demo-msg').textContent = '¡Interacción en vivo funcionando dentro del Sandbox CSP aislado!'">
      Probar Interacción en Vivo
    </button>
    <p id="demo-msg" style="color:#4ade80;font-weight:600;margin-top:12px;"></p>
  </div>
</body>
</html>"""
            archivo_entrada = staging_dir / punto_entrada_limpio
            archivo_entrada.parent.mkdir(parents=True, exist_ok=True)
            archivo_entrada.write_text(html_final, encoding="utf-8")

        # Reemplazo atómico: Borrar la versión anterior y mover únicamente la versión validada
        destino_proyecto = SANDBOX_ROOT / str(proyecto.id)
        if destino_proyecto.exists():
            shutil.rmtree(destino_proyecto)
        shutil.move(str(staging_dir), str(destino_proyecto))

        return f"sandbox_projects/{proyecto.id}"

    except ValidationError as exc:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        proyecto.estado_procesamiento_zip = "ERROR"
        proyecto.ultimo_error_zip = exc.messages[0]
        proyecto.save(update_fields=["estado_procesamiento_zip", "ultimo_error_zip"])
        raise
    except Exception as exc:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        raise ValidationError(f"Error al procesar el paquete del proyecto: {exc}")
