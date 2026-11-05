"""
Módulo 5: Servicio del Agente IA Guardián y Mentor de Proyectos (apps/asistente/services.py)

Propósito del Agente Aegis IA:
1. Actuar como un Instructor / Mentor Inteligente del SENA ADSO que responde directamente
   a la idea o inquietud que envía el aprendiz, guiándolo paso a paso para estructurar,
   mejorar y aterrizar el alcance de su proyecto formativo.
2. Garantizar Cero Proyectos Repetidos en el SENA (Vectores 768-D en PostgreSQL + similitud léxica):
   - Si la idea o título choca con otro proyecto existente, explica el conflicto y le propone
     al Grupo Scrum giros/enfoques diferenciadores concretos sobre su misma temática.
   - Si la idea es única, analiza la propuesta enviada por el aprendiz, sugiere mejoras al título,
     define módulos funcionales MVP específicos para su idea, actores, reglas de negocio y stack.
3. Limitaciones Estipuladas del Agente:
   - Guía pedagógicamente la idea, el alcance funcional, los módulos y la originalidad del proyecto.
   - NO escribe el código fuente completo de la entrega ni dibuja por ellos los diagramas finales
     (les explica cómo estructurar la lógica conceptualmente para que el Grupo Scrum construya su solución).
"""

import hashlib
import math
import re
from difflib import SequenceMatcher
from apps.proyectos.models import Proyecto
from apps.usuarios.models import Usuario

STOPWORDS_ES = {
    "de", "la", "el", "en", "y", "a", "los", "del", "se", "las", "por", "un",
    "para", "con", "no", "una", "su", "al", "lo", "como", "mas", "pero", "sus",
    "le", "ya", "o", "este", "si", "porque", "esta", "entre", "cuando", "muy",
    "sin", "sobre", "tambien", "me", "hasta", "hay", "donde", "quien", "desde",
    "sistema", "aplicacion", "plataforma", "web", "app", "software", "gestion",
    "control", "proyecto", "sena", "adso", "mediante", "digital", "hacer",
    "queremos", "quiero", "tenemos", "idea", "crear", "desarrollar", "nuestro",
    "nuestra", "grupo", "scrum", "para", "que", "permita", "permite", "ayuda",
}

# Clústeres semánticos de dominios frecuentes en proyectos ADSO para detectar ideas equivalentes
CLUSTERS_DOMINIO_SENA = {
    "DOM_INVENTARIO_BODEGA": {
        "inventario", "inventarios", "bodega", "almacen", "stock", "existencias",
        "kardex", "mercancia", "insumos", "suministros", "ferreteria", "herramientas",
    },
    "DOM_SALUD_CITAS": {
        "cita", "citas", "medica", "medicas", "medico", "paciente", "pacientes",
        "consultorio", "clinica", "hospital", "odontologia", "historia_clinica", "eps", "ips",
    },
    "DOM_PARQUEADERO_VEHICULOS": {
        "parqueadero", "estacionamiento", "parking", "vehiculo", "vehiculos",
        "motos", "celdas", "tarifa_parqueo", "placa", "peaje",
    },
    "DOM_RESTAURANTE_COMANDAS": {
        "restaurante", "comanda", "comandas", "menu", "platos", "mesero",
        "cocina", "gastronomia", "cafeteria", "domicilios", "reservas_mesa",
    },
    "DOM_FACTURACION_POS": {
        "facturacion", "factura", "pos", "caja", "ventas", "punto_venta",
        "recibo", "cotizacion", "cajero", "tienda", "minimercado",
    },
    "DOM_AGRO_CAMPO": {
        "agro", "agricola", "cultivo", "cultivos", "finca", "cosecha",
        "campesino", "ganaderia", "ganado", "cafe", "riego", "invernadero", "humedad",
    },
    "DOM_VETERINARIA_MASCOTAS": {
        "veterinaria", "mascota", "mascotas", "perros", "gatos", "vacunacion",
        "adopcion", "peluqueria_canina", "clinica_veterinaria", "zoonosis",
    },
    "DOM_ASISTENCIA_ACCESO": {
        "asistencia", "biometrico", "huella", "acceso", "ingreso",
        "carnet", "porteria", "visitantes", "minutera",
    },
    "DOM_BIBLIOTECA_PRESTAMOS": {
        "biblioteca", "libros", "prestamo", "lectura", "editorial", "ambientes",
    },
    "DOM_GIMNASIO_FITNESS": {
        "gimnasio", "rutinas", "entrenamiento", "fitness", "membresia", "entrenador", "deporte",
    },
    "DOM_EDUCACION_ACADEMICO": {
        "colegio", "notas", "calificaciones", "estudiantes", "matriculas", "cursos",
        "aula", "evaluaciones", "tutorias", "desercion",
    },
    "DOM_TRANSPORTE_LOGISTICA": {
        "transporte", "rutas", "envios", "flota", "conductores", "despacho",
        "logistica", "paqueteria", "mensajeria", "geolocalizacion",
    },
    "DOM_ENERGIA_SOSTENIBILIDAD": {
        "solar", "energia", "fotovoltaica", "reciclaje", "residuos", "ambiental",
        "carbono", "consumo_electrico", "sostenible",
    },
    "DOM_TURISMO_HOTELES": {
        "hotel", "hospedaje", "turismo", "reservas", "habitaciones", "viajes", "guia_turistica",
    },
    "DOM_BELLEZA_BARBERIA": {
        "barberia", "peluqueria", "spa", "estetica", "agenda", "barbero", "estilista", "turnos",
    },
}


def _normalizar_sin_tildes(texto: str) -> str:
    reemplazos = str.maketrans("áéíóúüÁÉÍÓÚÜ", "aeiouuAEIOUU")
    return (texto or "").translate(reemplazos).lower()


def generar_embedding_768(texto: str) -> list[float]:
    """
    Genera un vector normalizado de 768 dimensiones para almacenar en PostgreSQL (`embedding_idea`).
    Combina clústeres semánticos de dominio SENA ADSO + raíces léxicas + bigramas
    para detectar ideas repetidas incluso cuando usan sinónimos.
    """
    limpio = re.sub(r"[^a-zñ0-9\s]", " ", _normalizar_sin_tildes(texto))
    palabras = [p for p in limpio.split() if len(p) > 2 and p not in STOPWORDS_ES]
    vector = [0.0] * 768

    if not palabras:
        return vector

    tokens_sem = list(palabras)
    tokens_sem.extend(f"stem_{p[:5]}" for p in palabras if len(p) >= 5)
    for i in range(len(palabras) - 1):
        tokens_sem.append(f"bi_{palabras[i]}_{palabras[i + 1]}")

    conjunto_palabras = set(palabras) | {p[:6] for p in palabras if len(p) >= 6}
    for nombre_cluster, vocabulario in CLUSTERS_DOMINIO_SENA.items():
        coincidencias_cluster = sum(
            1 for voc in vocabulario if voc in conjunto_palabras or voc[:6] in conjunto_palabras
        )
        if coincidencias_cluster > 0:
            for _ in range(coincidencias_cluster * 3):
                tokens_sem.append(nombre_cluster)

    for token in tokens_sem:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx1 = int.from_bytes(digest[0:2], "big") % 768
        idx2 = int.from_bytes(digest[2:4], "big") % 768
        signo = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[idx1] += 1.0
        vector[idx2] += 0.5 * signo

    norma = math.sqrt(sum(v * v for v in vector))
    if norma > 0:
        vector = [round(v / norma, 6) for v in vector]
    return vector


def similitud_coseno(v1: list[float] | None, v2: list[float] | None) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = math.sqrt(sum(a * a for a in v1))
    n2 = math.sqrt(sum(b * b for b in v2))
    if n1 == 0 or n2 == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (n1 * n2)))


def buscar_proyectos_similares(
    titulo_propuesto: str,
    idea_propuesta: str,
    excluir_grupo_id=None,
    umbral_similitud: float = 0.50,
) -> list[dict]:
    """
    Compara el título e idea propuestos contra los proyectos existentes en PostgreSQL
    combinando similitud vectorial de 768 dimensiones (`embedding_idea`) y similitud léxica.
    """
    proyectos = Proyecto.objects.select_related("ficha", "grupo_scrum").exclude(
        estado__in=[
            Proyecto.EstadoProyecto.ELIMINADO_POR_GRUPO,
            Proyecto.EstadoProyecto.RETIRADO_INSTRUCTOR,
        ]
    )
    if excluir_grupo_id:
        proyectos = proyectos.exclude(grupo_scrum_id=excluir_grupo_id)

    titulo_norm = _normalizar_sin_tildes(titulo_propuesto).strip()
    idea_norm = _normalizar_sin_tildes(idea_propuesta).strip()
    vec_consulta = generar_embedding_768(f"{titulo_norm} {idea_norm}")

    coincidencias = []
    for proy in proyectos:
        proy_titulo_norm = _normalizar_sin_tildes(proy.titulo).strip()
        proy_idea_norm = _normalizar_sin_tildes(proy.introduccion).strip()

        sim_titulo = SequenceMatcher(None, titulo_norm, proy_titulo_norm).ratio() if titulo_norm else 0.0
        sim_idea = SequenceMatcher(None, idea_norm, proy_idea_norm).ratio() if idea_norm else 0.0
        vec_proy = proy.embedding_idea or generar_embedding_768(
            f"{proy.titulo} {proy.introduccion}"
        )
        sim_vector = similitud_coseno(vec_consulta, vec_proy)

        puntaje = max(sim_titulo, sim_idea, sim_vector)

        if (
            titulo_norm
            and len(titulo_norm) >= 5
            and (
                titulo_norm in proy_titulo_norm
                or proy_titulo_norm in titulo_norm
            )
        ):
            puntaje = max(puntaje, 0.88)

        if puntaje >= umbral_similitud:
            coincidencias.append(
                {
                    "proyecto_id": str(proy.id),
                    "titulo": proy.titulo,
                    "introduccion": proy.introduccion,
                    "ficha": proy.ficha.numero,
                    "grupo_scrum": proy.grupo_scrum.nombre_grupo,
                    "similitud": round(puntaje * 100, 1),
                }
            )

    coincidencias.sort(key=lambda x: x["similitud"], reverse=True)
    return coincidencias[:5]


def procesar_consulta_agente_guardian(
    aprendiz: Usuario,
    mensaje: str,
    titulo_propuesto: str = "",
    historial: list[dict] | None = None,
) -> dict:
    """
    Ejecuta el Grafo de Estados del Agente Aegis IA (`apps/asistente/graph.py`).
    """
    from .graph import ejecutar_grafo_agente_guardian

    return ejecutar_grafo_agente_guardian(
        aprendiz=aprendiz,
        mensaje=mensaje,
        titulo_propuesto=titulo_propuesto,
        historial=historial or [],
    )
