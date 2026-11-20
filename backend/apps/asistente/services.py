"""
Módulo 5: Motor de Originalidad Guiada de Aegis IA (apps/asistente/services.py)

PRIORIDAD Nº 1 DE AEGIS: ORIGINALIDAD GUIADA
- Compara cualquier idea concreta contra TODOS los proyectos en PostgreSQL
  (todas las fichas, jornadas, trimestres e historial de proyectos archivados/retirados)
  y contra arquetipos saturados del SENA ADSO.
- Veredicto 100% determinista a partir de similitud semántica (768-D + clústeres de dominio +
  normalización canónica de sinónimos anti-evasión + similitud léxica), independiente del LLM.
- Respeta privacidad estricta: solo nombra proyectos públicamente publicados en la Vitrina;
  para proyectos borrador, privados o archivados explica el choque de forma general sin
  revelar títulos, grupos ni integrantes.
- Serializa escrituras de embeddings con bloqueo transaccional PostgreSQL (`pg_advisory_xact_lock`)
  para detectar colisiones simultáneas entre equipos.
"""

import hashlib
import math
import re
from difflib import SequenceMatcher
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction

from apps.proyectos.models import Proyecto
from apps.usuarios.models import Usuario

# =============================================================================
# UMBRALES CONFIGURABLES DE ORIGINALIDAD (Documentados y deterministas)
# =============================================================================
# - ORIGINAL (< 0.42): Sin choque relevante; la idea posee enfoque propio.
# - SIMILAR  (0.42 .. 0.679): Choque parcial (comparte dominio, problema o funciones);
#   Aegis guía diferenciación por usuario, problema, contexto, función o restricciones.
# - REPETIDA (>= 0.68): Choque fuerte (idea equivalente o renombrada con sinónimos);
#   Aegis guía replanteamiento manteniendo el interés temático del aprendiz.
UMBRAL_ORIGINAL_MAX = float(getattr(settings, "AEGIS_UMBRAL_SIMILAR", 0.42))
UMBRAL_SIMILAR = UMBRAL_ORIGINAL_MAX
UMBRAL_REPETIDA = float(getattr(settings, "AEGIS_UMBRAL_REPETIDA", 0.68))

# Clave de bloqueo transaccional PostgreSQL para registro concurrente de ideas/embeddings
LOCK_KEY_ORIGINALIDAD_PROYECTOS = 7042026

VEREDICTO_A_ETIQUETA_UI = {
    "SIN_VALIDAR": "Sin validar",
    "ORIGINAL": "Original",
    "SIMILAR": "Similar: por diferenciar",
    "REPETIDA": "Repetida: replantear",
}

STOPWORDS_ES = {
    "de", "la", "el", "en", "y", "a", "los", "del", "se", "las", "por", "un",
    "para", "con", "no", "una", "su", "al", "lo", "como", "mas", "pero", "sus",
    "le", "ya", "o", "este", "si", "porque", "esta", "entre", "cuando", "muy",
    "sin", "sobre", "tambien", "me", "hasta", "hay", "donde", "quien", "desde",
    "sistema", "aplicacion", "plataforma", "web", "app", "software", "gestion",
    "control", "proyecto", "sena", "adso", "mediante", "digital", "hacer",
    "queremos", "quiero", "tenemos", "idea", "crear", "desarrollar", "nuestro",
    "nuestra", "grupo", "scrum", "que", "permita", "permite", "ayuda", "ayudar",
    "gestionar", "administrar", "manejar", "manejo", "administracion", "herramienta",
    "solucion", "portal", "modulo", "basico", "sencillo", "sencilla", "pro",
}

# =============================================================================
# NORMALIZACIÓN CANÓNICA DE SINÓNIMOS (Anti-evasión semántica)
# Evita que cambiar palabras por sinónimos o renombrar la app oculte una idea repetida.
# =============================================================================
SINONIMOS_CANONICOS = {
    # Inventario y tiendas
    "inventario": "c_inventario", "inventarios": "c_inventario", "stock": "c_inventario",
    "existencias": "c_inventario", "kardex": "c_inventario", "mercancia": "c_inventario",
    "mercancias": "c_inventario", "bodega": "c_inventario", "almacen": "c_inventario",
    "insumos": "c_inventario", "productos": "c_inventario", "surtido": "c_inventario",
    "tienda": "c_comercio", "tiendas": "c_comercio", "minimercado": "c_comercio",
    "abarrotes": "c_comercio", "supermercado": "c_comercio", "comercio": "c_comercio",
    "negocio": "c_comercio", "miscelanea": "c_comercio", "tendero": "c_comercio",
    "ventas": "c_venta", "venta": "c_venta", "facturacion": "c_venta",
    "factura": "c_venta", "caja": "c_venta", "pos": "c_venta", "cobro": "c_venta",
    # Salud y citas
    "cita": "c_cita", "citas": "c_cita", "turno": "c_cita", "turnos": "c_cita",
    "agenda": "c_cita", "agendamiento": "c_cita", "reserva": "c_cita", "reservas": "c_cita",
    "programacion": "c_cita", "horario": "c_cita", "horarios": "c_cita",
    "medico": "c_salud", "medica": "c_salud", "medicas": "c_salud", "salud": "c_salud",
    "clinica": "c_salud", "consultorio": "c_salud", "hospital": "c_salud",
    "paciente": "c_salud", "pacientes": "c_salud", "odontologia": "c_salud",
    "odontologicas": "c_salud", "dental": "c_salud", "triage": "c_salud", "triaje": "c_salud",
    # Agro y monitoreo
    "agro": "c_agro", "agricola": "c_agro", "cultivo": "c_agro", "cultivos": "c_agro",
    "finca": "c_agro", "fincas": "c_agro", "cafe": "c_agro", "caficultor": "c_agro",
    "caficultores": "c_agro", "cafetal": "c_agro", "campesino": "c_agro", "cosecha": "c_agro",
    "riego": "c_riego", "irrigacion": "c_riego", "humedad": "c_riego",
    "sensor": "c_sensor", "sensores": "c_sensor", "monitoreo": "c_sensor",
    "medicion": "c_sensor", "telemetria": "c_sensor",
    # Logística, despachos y domicilios
    "despacho": "c_logistica", "despachos": "c_logistica", "envio": "c_logistica",
    "envios": "c_logistica", "entrega": "c_logistica", "entregas": "c_logistica",
    "domicilio": "c_logistica", "domicilios": "c_logistica", "paquete": "c_logistica",
    "paqueteria": "c_logistica", "mensajeria": "c_logistica", "logistica": "c_logistica",
    "ruta": "c_ruta", "rutas": "c_ruta", "reparto": "c_ruta", "repartidor": "c_ruta",
    "flota": "c_ruta", "conductor": "c_ruta", "conductores": "c_ruta",
    "cooperativa": "c_cooperativa", "cooperativas": "c_cooperativa", "transporte": "c_ruta",
    # Belleza y barbería
    "barberia": "c_belleza", "barbero": "c_belleza", "peluqueria": "c_belleza",
    "estilista": "c_belleza", "salon": "c_belleza", "estetica": "c_belleza",
    "spa": "c_belleza", "corte": "c_belleza", "barba": "c_belleza",
    # Veterinaria y mascotas
    "veterinaria": "c_veterinaria", "mascota": "c_veterinaria", "mascotas": "c_veterinaria",
    "perro": "c_veterinaria", "perros": "c_veterinaria", "gato": "c_veterinaria",
    "gatos": "c_veterinaria", "vacunacion": "c_veterinaria", "animal": "c_veterinaria",
    # Restaurantes y comidas
    "restaurante": "c_comida", "comanda": "c_comida", "comandas": "c_comida",
    "menu": "c_comida", "mesero": "c_comida", "cocina": "c_comida",
    "cafeteria": "c_comida", "platos": "c_comida", "almuerzos": "c_comida",
    # Parqueaderos
    "parqueadero": "c_parqueo", "estacionamiento": "c_parqueo", "parking": "c_parqueo",
    "celdas": "c_parqueo", "placa": "c_parqueo", "vehiculo": "c_parqueo", "vehiculos": "c_parqueo",
    # Gimnasios
    "gimnasio": "c_fitness", "gym": "c_fitness", "rutinas": "c_fitness",
    "entrenamiento": "c_fitness", "membresia": "c_fitness", "entrenador": "c_fitness",
}

# Clústeres semánticos de dominios frecuentes en proyectos ADSO
CLUSTERS_DOMINIO_SENA = {
    "DOM_INVENTARIO_BODEGA": {
        "inventario", "inventarios", "bodega", "almacen", "stock", "existencias",
        "kardex", "mercancia", "insumos", "suministros", "ferreteria", "herramientas",
        "productos", "tienda", "minimercado", "abarrotes",
    },
    "DOM_SALUD_CITAS": {
        "medica", "medicas", "medico", "paciente", "pacientes",
        "consultorio", "clinica", "hospital", "odontologia", "odontologicas",
        "dental", "triage", "triaje", "salud", "eps", "ips",
    },
    "DOM_PARQUEADERO_VEHICULOS": {
        "parqueadero", "estacionamiento", "parking", "vehiculo", "vehiculos",
        "motos", "celdas", "tarifa", "placa", "peaje",
    },
    "DOM_RESTAURANTE_COMANDAS": {
        "restaurante", "comanda", "comandas", "menu", "platos", "mesero",
        "cocina", "gastronomia", "cafeteria", "almuerzos",
    },
    "DOM_FACTURACION_POS": {
        "facturacion", "factura", "pos", "caja", "ventas", "venta",
        "recibo", "cotizacion", "cajero", "tienda", "minimercado",
    },
    "DOM_AGRO_CAMPO": {
        "agro", "agricola", "cultivo", "cultivos", "finca", "cosecha",
        "campesino", "ganaderia", "ganado", "cafe", "caficultor", "caficultores",
        "riego", "irrigacion", "invernadero", "humedad", "sensor", "sensores",
    },
    "DOM_VETERINARIA_MASCOTAS": {
        "veterinaria", "mascota", "mascotas", "perro", "perros", "gato", "gatos",
        "vacunacion", "adopcion", "animal", "animales",
    },
    "DOM_ASISTENCIA_ACCESO": {
        "asistencia", "biometrico", "huella", "acceso", "ingreso",
        "carnet", "porteria", "visitantes",
    },
    "DOM_BIBLIOTECA_PRESTAMOS": {
        "biblioteca", "libros", "prestamo", "prestamos", "lectura", "editorial",
    },
    "DOM_GIMNASIO_FITNESS": {
        "gimnasio", "gym", "rutinas", "entrenamiento", "fitness", "membresia", "entrenador",
    },
    "DOM_EDUCACION_ACADEMICO": {
        "colegio", "notas", "calificaciones", "estudiantes", "matriculas", "cursos",
        "aula", "evaluaciones", "tutorias", "desercion",
    },
    "DOM_TRANSPORTE_LOGISTICA": {
        "transporte", "ruta", "rutas", "envio", "envios", "flota", "conductor",
        "conductores", "despacho", "despachos", "entrega", "entregas", "logistica",
        "paqueteria", "mensajeria", "domicilio", "domicilios", "cooperativa", "cooperativas",
    },
    "DOM_ENERGIA_SOSTENIBILIDAD": {
        "solar", "energia", "fotovoltaica", "reciclaje", "residuos", "ambiental",
        "carbono", "sostenible",
    },
    "DOM_TURISMO_HOTELES": {
        "hotel", "hospedaje", "turismo", "reservas", "habitaciones", "viajes",
    },
    "DOM_BELLEZA_BARBERIA": {
        "barberia", "peluqueria", "spa", "estetica", "barbero", "estilista", "salon", "corte",
    },
}

DOMINIO_ETIQUETA_HUMANA = {
    "DOM_INVENTARIO_BODEGA": "inventario y control de existencias en comercio/bodega",
    "DOM_SALUD_CITAS": "agendamiento de citas y atención en salud",
    "DOM_PARQUEADERO_VEHICULOS": "control de parqueadero y vehículos",
    "DOM_RESTAURANTE_COMANDAS": "comandas, menú y pedidos de restaurante",
    "DOM_FACTURACION_POS": "facturación, caja y ventas en tienda",
    "DOM_AGRO_CAMPO": "monitoreo agrícola, cultivos y riego",
    "DOM_VETERINARIA_MASCOTAS": "gestión veterinaria y cuidado de mascotas",
    "DOM_ASISTENCIA_ACCESO": "control de asistencia y acceso",
    "DOM_BIBLIOTECA_PRESTAMOS": "préstamo de libros o recursos en biblioteca",
    "DOM_GIMNASIO_FITNESS": "gestión de membresías y rutinas de gimnasio",
    "DOM_EDUCACION_ACADEMICO": "gestión escolar de notas y cursos",
    "DOM_TRANSPORTE_LOGISTICA": "despachos, rutas y entregas logísticas",
    "DOM_ENERGIA_SOSTENIBILIDAD": "sostenibilidad, reciclaje o energía",
    "DOM_TURISMO_HOTELES": "reservas hoteleras y turismo",
    "DOM_BELLEZA_BARBERIA": "agenda de turnos en barbería o peluquería",
}

CONCEPTO_ETIQUETA_HUMANA = {
    "c_inventario": "control de inventario/stock",
    "c_comercio": "gestión para tienda o comercio",
    "c_venta": "registro de ventas y caja",
    "c_cita": "agendamiento de citas o turnos",
    "c_salud": "atención de pacientes en salud",
    "c_agro": "operación agrícola o de cultivos",
    "c_riego": "control de riego y humedad",
    "c_sensor": "monitoreo con sensores",
    "c_logistica": "gestión de despachos, envíos o domicilios",
    "c_ruta": "seguimiento de rutas y entregas",
    "c_cooperativa": "operación de cooperativas",
    "c_belleza": "servicios de barbería o salón de belleza",
    "c_veterinaria": "gestión de clínica veterinaria o mascotas",
    "c_comida": "pedidos y comandas de restaurante",
    "c_parqueo": "control de celdas y parqueadero",
    "c_fitness": "membresías y rutinas de gimnasio",
}

# Referencia histórica de proyectos clásicos muy repetidos en cohortes ADSO del SENA
# (tratados como historial interno no público: nunca revelan nombres ni integrantes).
CATALOGO_HISTORICO_SENA_SATURADO = [
    {
        "dominio": "DOM_INVENTARIO_BODEGA",
        "texto": "sistema de inventario control de stock existencias productos ventas y entradas salidas para una tienda de barrio o minimercado",
        "resumen": "control genérico de inventario, stock y ventas en una tienda",
    },
    {
        "dominio": "DOM_BELLEZA_BARBERIA",
        "texto": "agenda de citas y turnos para una barberia o peluqueria con reserva de horarios de clientes y barberos",
        "resumen": "agenda genérica de citas y turnos para barbería o peluquería",
    },
    {
        "dominio": "DOM_RESTAURANTE_COMANDAS",
        "texto": "sistema de pedidos comandas menu mesas y facturacion para un restaurante o cafeteria",
        "resumen": "gestión genérica de comandas, menú y mesas de restaurante",
    },
    {
        "dominio": "DOM_PARQUEADERO_VEHICULOS",
        "texto": "control de ingreso salida placas tarifas y celdas disponibles para un parqueadero de carros y motos",
        "resumen": "control genérico de entradas, salidas y tarifas de parqueadero",
    },
    {
        "dominio": "DOM_GIMNASIO_FITNESS",
        "texto": "gestion de membresias pagos asistencia y rutinas de entrenamiento para un gimnasio",
        "resumen": "gestión genérica de membresías y rutinas en un gimnasio",
    },
    {
        "dominio": "DOM_VETERINARIA_MASCOTAS",
        "texto": "gestion de citas historia clinica vacunacion y clientes para una veterinaria de mascotas",
        "resumen": "gestión genérica de citas e historia clínica para veterinaria",
    },
]


def _normalizar_sin_tildes(texto: str) -> str:
    reemplazos = str.maketrans("áéíóúüÁÉÍÓÚÜ", "aeiouuAEIOUU")
    return (texto or "").translate(reemplazos).lower()


def _extraer_rasgos_semanticos(texto: str) -> dict:
    """Extrae palabras limpias, conceptos canónicos (anti-evasión) y clústeres de dominio."""
    limpio = re.sub(r"[^a-zñ0-9\s]", " ", _normalizar_sin_tildes(texto))
    palabras = [p for p in limpio.split() if len(p) > 2 and p not in STOPWORDS_ES]

    conceptos = set()
    for p in palabras:
        if p in SINONIMOS_CANONICOS:
            conceptos.add(SINONIMOS_CANONICOS[p])

    conjunto_palabras = set(palabras) | {p[:6] for p in palabras if len(p) >= 6}
    dominios = set()
    for nombre_cluster, vocabulario in CLUSTERS_DOMINIO_SENA.items():
        if any(voc in conjunto_palabras or voc[:6] in conjunto_palabras for voc in vocabulario):
            dominios.add(nombre_cluster)

    return {
        "palabras": palabras,
        "conceptos": conceptos,
        "dominios": dominios,
    }


def generar_embedding_768(texto: str) -> list[float]:
    """
    Genera un vector normalizado de 768 dimensiones para almacenar en PostgreSQL (`embedding_idea`).
    Combina:
    - Clústeres semánticos de dominio SENA ADSO
    - Conceptos canónicos de sinónimos (anti-evasión cuando cambian palabras por sinónimos)
    - Raíces léxicas y bigramas (para capturar diferenciaciones reales de contexto/función)
    """
    rasgos = _extraer_rasgos_semanticos(texto)
    palabras = rasgos["palabras"]
    vector = [0.0] * 768

    if not palabras:
        return vector

    tokens_sem: list[str] = list(palabras)
    tokens_sem.extend(f"stem_{p[:5]}" for p in palabras if len(p) >= 5)
    for i in range(len(palabras) - 1):
        tokens_sem.append(f"bi_{palabras[i]}_{palabras[i + 1]}")

    # Pesos moderados para conceptos canónicos (resistencia a sinónimos sin aplastar diferenciadores reales)
    for concepto in rasgos["conceptos"]:
        tokens_sem.extend([concepto] * 2)

    # Pesos por clústeres de dominio detectados
    conjunto_palabras = set(palabras) | {p[:6] for p in palabras if len(p) >= 6}
    for nombre_cluster, vocabulario in CLUSTERS_DOMINIO_SENA.items():
        coincidencias_cluster = sum(
            1 for voc in vocabulario if voc in conjunto_palabras or voc[:6] in conjunto_palabras
        )
        if coincidencias_cluster > 0:
            peso = min(coincidencias_cluster * 2, 4)
            tokens_sem.extend([nombre_cluster] * peso)

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


def _es_proyecto_publico(proy: Proyecto) -> bool:
    """
    Regla de privacidad: un proyecto SOLO puede mencionarse por nombre/ficha/grupo
    si está públicamente publicado en la Vitrina. Borradores, proyectos de solo ficha
    y proyectos archivados/retirados son privados.
    """
    grupo_estado = getattr(proy.grupo_scrum, "estado", "")
    return (
        grupo_estado == "PUBLICADO"
        and proy.estado == Proyecto.EstadoProyecto.PUBLICADO
        and proy.visibilidad == Proyecto.Visibilidad.PUBLICO
    )


def _calcular_puntaje_y_ejes(
    titulo_norm: str,
    idea_norm: str,
    vec_consulta: list[float],
    rasgos_consulta: dict,
    ref_titulo: str,
    ref_idea: str,
    vec_ref: list[float],
    es_arquetipo_generico: bool = False,
) -> tuple[float, dict]:
    ref_titulo_norm = _normalizar_sin_tildes(ref_titulo).strip()
    ref_idea_norm = _normalizar_sin_tildes(ref_idea).strip()
    rasgos_ref = _extraer_rasgos_semanticos(f"{ref_titulo_norm} {ref_idea_norm}")

    # Similitud de título (solo cuando ambos títulos existen y son comparables)
    sim_titulo = 0.0
    if titulo_norm and ref_titulo_norm and len(titulo_norm) >= 4 and len(ref_titulo_norm) >= 4:
        ratio_tit = SequenceMatcher(None, titulo_norm, ref_titulo_norm).ratio()
        toks_tit_q = set(_extraer_rasgos_semanticos(titulo_norm)["palabras"])
        toks_tit_r = set(_extraer_rasgos_semanticos(ref_titulo_norm)["palabras"])
        if ratio_tit >= 0.72 or (toks_tit_q and toks_tit_r and (toks_tit_q & toks_tit_r)):
            sim_titulo = ratio_tit

    # Similitud léxica por tokens/raíces relevantes (evita falsos positivos por letras comunes en español)
    stems_q = {p[:5] for p in rasgos_consulta["palabras"]}
    stems_r = {p[:5] for p in rasgos_ref["palabras"]}
    sim_lexica = 0.0
    if stems_q and stems_r:
        inter_s = len(stems_q & stems_r)
        union_s = len(stems_q | stems_r)
        sim_lexica = inter_s / max(union_s, 1)

    sim_vector = similitud_coseno(vec_consulta, vec_ref)

    dominios_comunes = sorted(rasgos_consulta["dominios"] & rasgos_ref["dominios"])
    conceptos_comunes = sorted(rasgos_consulta["conceptos"] & rasgos_ref["conceptos"])

    # Palabras genuinamente diferenciadoras (ni sinónimo del dominio ni presentes en la referencia)
    stems_ref = {p[:5] for p in rasgos_ref["palabras"]}
    palabras_diferenciadoras = [
        p for p in rasgos_consulta["palabras"]
        if p not in SINONIMOS_CANONICOS and p[:5] not in stems_ref
    ]

    # Similitud canónica anti-evasión (Jaccard / cobertura sobre conceptos normalizados)
    sim_canonica = 0.0
    if rasgos_consulta["conceptos"] and rasgos_ref["conceptos"] and conceptos_comunes:
        inter = len(conceptos_comunes)
        union = len(rasgos_consulta["conceptos"] | rasgos_ref["conceptos"])
        cobertura_consulta = inter / max(len(rasgos_consulta["conceptos"]), 1)
        cobertura_ref = inter / max(len(rasgos_ref["conceptos"]), 1)
        jaccard = inter / max(union, 1)
        factor_diff = min(len(palabras_diferenciadoras), 10) * 0.065

        # Si solo comparten un concepto genérico (ej: c_cita) en dominios distintos (salud vs barbería),
        # no inflar similitud canónica
        if not dominios_comunes and inter < 2:
            sim_canonica = 0.0
        else:
            base_can = 0.45 * cobertura_consulta + 0.30 * jaccard + 0.25 * cobertura_ref
            sim_canonica = max(0.0, base_can - factor_diff)
            # Anti-evasión fuerte: mismos conceptos clave con pocos o nulos diferenciadores reales
            if inter >= 2 and cobertura_consulta >= 0.75 and len(palabras_diferenciadoras) <= 3:
                sim_canonica = max(sim_canonica, 0.76)
            elif (
                es_arquetipo_generico
                and dominios_comunes
                and inter >= 1
                and len(palabras_diferenciadoras) <= 2
            ):
                sim_canonica = max(sim_canonica, 0.72)

    puntaje = max(sim_titulo, sim_lexica, sim_vector, sim_canonica)

    # Si la idea propone un enfoque fuertemente diferenciado (>= 5 palabras diferenciadoras reales)
    # contra un arquetipo genérico histórico, descontar penalización de saturación para permitir ORIGINAL/SIMILAR
    if es_arquetipo_generico and len(palabras_diferenciadoras) >= 5:
        descuento = min((len(palabras_diferenciadoras) - 4) * 0.065, 0.35)
        puntaje = max(0.0, puntaje - descuento)

    # Si no comparten ningún dominio ni concepto ni raíz relevante, descartar ruido de hashing
    if not dominios_comunes and not conceptos_comunes and sim_lexica < 0.15 and sim_titulo < 0.72:
        puntaje = min(puntaje, 0.28)

    if (
        titulo_norm
        and ref_titulo_norm
        and len(titulo_norm) >= 5
        and (titulo_norm in ref_titulo_norm or ref_titulo_norm in titulo_norm)
    ):
        puntaje = max(puntaje, 0.88)

    ejes = {
        "dominios_comunes": [DOMINIO_ETIQUETA_HUMANA.get(d, d) for d in dominios_comunes],
        "conceptos_comunes": [CONCEPTO_ETIQUETA_HUMANA.get(c, c) for c in conceptos_comunes],
        "sim_vector": round(sim_vector * 100, 1),
        "sim_canonica": round(sim_canonica * 100, 1),
        "palabras_diferenciadoras": len(palabras_diferenciadoras),
    }
    return min(1.0, puntaje), ejes


def evaluar_originalidad_idea(
    titulo_propuesto: str,
    idea_propuesta: str,
    excluir_grupo_id=None,
    umbral_similar: float | None = None,
    umbral_repetida: float | None = None,
) -> dict:
    """
    Evaluación determinista de originalidad en 3 niveles:
    - ORIGINAL  (< umbral_similar)
    - SIMILAR   (>= umbral_similar y < umbral_repetida)
    - REPETIDA  (>= umbral_repetida)

    Compara contra TODOS los proyectos de TODAS las fichas, jornadas y trimestres
    (incluyendo proyectos archivados/retirados por regla No-Delete) y contra
    arquetipos históricos saturados del SENA.
    Aplica filtro estricto de privacidad para proyectos no públicos.
    """
    u_sim = UMBRAL_SIMILAR if umbral_similar is None else float(umbral_similar)
    u_rep = UMBRAL_REPETIDA if umbral_repetida is None else float(umbral_repetida)

    titulo_norm = _normalizar_sin_tildes(titulo_propuesto).strip()
    idea_norm = _normalizar_sin_tildes(idea_propuesta).strip()
    texto_combinado = f"{titulo_norm} {idea_norm}".strip()
    vec_consulta = generar_embedding_768(texto_combinado)
    rasgos_consulta = _extraer_rasgos_semanticos(texto_combinado)

    # 1. Comparar contra TODOS los proyectos en PostgreSQL (todas las fichas, jornadas, archivados)
    proyectos_qs = Proyecto.objects.select_related("ficha", "grupo_scrum").all()
    if excluir_grupo_id:
        proyectos_qs = proyectos_qs.exclude(grupo_scrum_id=excluir_grupo_id)

    coincidencias = []
    for proy in proyectos_qs:
        vec_proy = proy.embedding_idea or generar_embedding_768(f"{proy.titulo} {proy.introduccion}")
        puntaje, ejes = _calcular_puntaje_y_ejes(
            titulo_norm=titulo_norm,
            idea_norm=idea_norm,
            vec_consulta=vec_consulta,
            rasgos_consulta=rasgos_consulta,
            ref_titulo=proy.titulo,
            ref_idea=proy.introduccion,
            vec_ref=vec_proy,
        )

        if puntaje >= u_sim:
            es_publico = _es_proyecto_publico(proy)
            nivel = "REPETIDA" if puntaje >= u_rep else "SIMILAR"
            item = {
                "origen": "repositorio_sena",
                "es_publico": es_publico,
                "nivel_choque": nivel,
                "similitud": round(puntaje * 100, 1),
                "dominios_comunes": ejes["dominios_comunes"],
                "conceptos_comunes": ejes["conceptos_comunes"],
            }
            if es_publico:
                item.update(
                    {
                        "proyecto_id": str(proy.id),
                        "titulo": proy.titulo,
                        "ficha": proy.ficha.numero,
                        "jornada": proy.ficha.jornada,
                        "grupo_scrum": proy.grupo_scrum.nombre_grupo,
                    }
                )
            else:
                # Privacidad estricta: no exponer título, ficha, grupo ni integrantes
                item.update(
                    {
                        "proyecto_id": None,
                        "titulo": None,
                        "ficha": None,
                        "jornada": None,
                        "grupo_scrum": None,
                        "resumen_privado": (
                            "Existe un proyecto no público o histórico en el repositorio SENA "
                            "con el mismo enfoque central."
                        ),
                    }
                )
            coincidencias.append(item)

    # 2. Comparar contra arquetipos históricos saturados del SENA (solo si comparte el mismo dominio)
    for arq in CATALOGO_HISTORICO_SENA_SATURADO:
        if arq["dominio"] not in rasgos_consulta["dominios"]:
            continue
        vec_arq = generar_embedding_768(arq["texto"])
        puntaje, ejes = _calcular_puntaje_y_ejes(
            titulo_norm="",
            idea_norm=texto_combinado,
            vec_consulta=vec_consulta,
            rasgos_consulta=rasgos_consulta,
            ref_titulo="",
            ref_idea=arq["texto"],
            vec_ref=vec_arq,
            es_arquetipo_generico=True,
        )
        if puntaje >= u_sim:
            nivel = "REPETIDA" if puntaje >= u_rep else "SIMILAR"
            coincidencias.append(
                {
                    "origen": "historico_sena_saturado",
                    "es_publico": False,
                    "nivel_choque": nivel,
                    "similitud": round(puntaje * 100, 1),
                    "dominios_comunes": ejes["dominios_comunes"] or [DOMINIO_ETIQUETA_HUMANA.get(arq["dominio"], arq["dominio"])],
                    "conceptos_comunes": ejes["conceptos_comunes"],
                    "proyecto_id": None,
                    "titulo": None,
                    "ficha": None,
                    "jornada": None,
                    "grupo_scrum": None,
                    "resumen_privado": f"un enfoque altamente repetido en cohortes SENA ({arq['resumen']})",
                }
            )

    # Ordenar primero por mayor similitud (desempate a favor del repositorio real SENA)
    coincidencias.sort(key=lambda x: (x["similitud"], x["origen"] == "repositorio_sena"), reverse=True)
    top_coincidencias = coincidencias[:5]

    if not top_coincidencias:
        veredicto = "ORIGINAL"
        puntaje_max = 0.0
    else:
        puntaje_max = max(c["similitud"] for c in top_coincidencias)
        veredicto = "REPETIDA" if (puntaje_max / 100.0) >= u_rep else "SIMILAR"

    principal = top_coincidencias[0] if top_coincidencias else None
    explicacion = {
        "dominios_comunes": principal["dominios_comunes"] if principal else [],
        "conceptos_comunes": principal["conceptos_comunes"] if principal else [],
        "motivo": _construir_motivo_honesto(veredicto, principal),
    }

    return {
        "veredicto": veredicto,
        "estado_ui": VEREDICTO_A_ETIQUETA_UI[veredicto],
        "es_idea_unica": veredicto == "ORIGINAL",
        "puntaje_max": puntaje_max,
        "umbrales": {
            "similar": round(u_sim * 100, 1),
            "repetida": round(u_rep * 100, 1),
        },
        "coincidencias": top_coincidencias,
        "explicacion_choque": explicacion,
        "embedding": vec_consulta,
    }


def _construir_motivo_honesto(veredicto: str, principal: dict | None) -> str:
    if veredicto == "ORIGINAL" or not principal:
        return "No se encontraron coincidencias relevantes en el repositorio institucional."

    partes = []
    if principal.get("dominios_comunes"):
        partes.append(f"el mismo dominio ({', '.join(principal['dominios_comunes'][:2])})")
    if principal.get("conceptos_comunes"):
        partes.append(f"funciones o conceptos equivalentes ({', '.join(principal['conceptos_comunes'][:3])})")

    detalle_ejes = " y ".join(partes) if partes else "el problema central y la funcionalidad propuesta"

    if principal.get("es_publico") and principal.get("titulo"):
        ref = f"el proyecto publicado «{principal['titulo']}» (Ficha {principal['ficha']})"
    elif principal.get("origen") == "historico_sena_saturado":
        ref = principal.get("resumen_privado", "un enfoque muy repetido en el SENA")
    else:
        ref = "un proyecto existente en el repositorio institucional (no público)"

    intensidad = "coincidencia fuerte" if veredicto == "REPETIDA" else "coincidencia parcial"
    return f"Se detectó una {intensidad} ({principal['similitud']}%) con {ref} porque comparten {detalle_ejes}."


def buscar_proyectos_similares(
    titulo_propuesto: str,
    idea_propuesta: str,
    excluir_grupo_id=None,
    umbral_similitud: float | None = None,
) -> list[dict]:
    """
    Wrapper compatible que retorna la lista sanitizada de coincidencias
    (incluyendo todas las fichas, jornadas y proyectos archivados, con privacidad aplicada).
    """
    eval_res = evaluar_originalidad_idea(
        titulo_propuesto=titulo_propuesto,
        idea_propuesta=idea_propuesta,
        excluir_grupo_id=excluir_grupo_id,
        umbral_similar=umbral_similitud,
    )
    return eval_res["coincidencias"]


def adquirir_bloqueo_originalidad():
    """
    Adquiere un bloqueo consultivo transaccional en PostgreSQL para evitar que dos equipos
    registren ideas idénticas simultáneamente antes de confirmar sus embeddings.
    """
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [LOCK_KEY_ORIGINALIDAD_PROYECTOS])


@transaction.atomic
def registrar_embedding_idea_con_bloqueo(
    grupo,
    titulo: str,
    introduccion: str,
    tecnologias: list | None = None,
    visibilidad: str = Proyecto.Visibilidad.FICHA,
    permitir_similar: bool = False,
) -> tuple[Proyecto, bool, dict]:
    """
    Registra o actualiza el proyecto del Grupo Scrum bajo bloqueo transaccional:
    - Serializa registros simultáneos para que el segundo equipo detecte al primero.
    - Solo guarda el embedding y marca ORIGINAL cuando la idea es aceptada.
    - Si hay colisión, lanza ValidationError con mensaje honesto y respetando privacidad.
    """
    adquirir_bloqueo_originalidad()

    titulo_limpio = " ".join((titulo or "").strip().split())
    intro_limpia = (introduccion or "").strip()

    colision_titulo = (
        Proyecto.objects.filter(titulo__iexact=titulo_limpio)
        .exclude(grupo_scrum=grupo)
        .select_related("ficha", "grupo_scrum")
        .first()
    )
    if colision_titulo:
        if _es_proyecto_publico(colision_titulo):
            raise ValidationError(
                f"El título '{titulo_limpio}' ya está registrado por el proyecto publicado "
                f"'{colision_titulo.titulo}' (Ficha {colision_titulo.ficha.numero})."
            )
        raise ValidationError(
            "Ya existe otro proyecto registrado en el SENA con ese mismo título. "
            "Elige un nombre propio para tu propuesta."
        )

    evaluacion = evaluar_originalidad_idea(
        titulo_propuesto=titulo_limpio,
        idea_propuesta=intro_limpia,
        excluir_grupo_id=grupo.id,
    )

    rechazado = (
        evaluacion["veredicto"] == "REPETIDA"
        or (evaluacion["veredicto"] == "SIMILAR" and not permitir_similar)
    )
    if rechazado:
        err = ValidationError(evaluacion["explicacion_choque"]["motivo"])
        err.evaluacion_originalidad = evaluacion
        raise err

    proyecto_existente = getattr(grupo, "proyecto", None)
    nuevo_estado = (
        proyecto_existente.estado
        if (proyecto_existente and proyecto_existente.estado == Proyecto.EstadoProyecto.PUBLICADO)
        else Proyecto.EstadoProyecto.IDEA_APROBADA
    )

    proyecto, creado = Proyecto.objects.update_or_create(
        grupo_scrum=grupo,
        defaults={
            "ficha": grupo.ficha,
            "titulo": titulo_limpio,
            "introduccion": intro_limpia,
            "embedding_idea": evaluacion["embedding"],
            "tecnologias": tecnologias if tecnologias is not None else (proyecto_existente.tecnologias if proyecto_existente else []),
            "visibilidad": visibilidad,
            "estado": nuevo_estado,
            "estado_originalidad": Proyecto.EstadoOriginalidad.ORIGINAL,
        },
    )
    return proyecto, creado, evaluacion


def procesar_consulta_agente_guardian(
    aprendiz: Usuario,
    mensaje: str,
    titulo_propuesto: str = "",
    historial: list[dict] | None = None,
) -> dict:
    """Ejecuta el Grafo de Originalidad Guiada de Aegis IA (`apps/asistente/graph.py`)."""
    from .graph import ejecutar_grafo_agente_guardian

    return ejecutar_grafo_agente_guardian(
        aprendiz=aprendiz,
        mensaje=mensaje,
        titulo_propuesto=titulo_propuesto,
        historial=historial or [],
    )
