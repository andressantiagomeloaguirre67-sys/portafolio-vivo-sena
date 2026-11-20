"""
Módulo 5: Grafo de Originalidad Guiada y Tutoría Socrática de Aegis IA (apps/asistente/graph.py)

PRIORIDAD Nº 1 DE AEGIS: ORIGINALIDAD GUIADA
1. Captura de la idea (`nodo_captura_idea`):
   Conversa con el aprendiz hasta que exista una idea concreta (problema, quién lo sufre y qué haría
   el sistema). Mientras NO haya idea concreta, PROHIBIDO validar originalidad ni mencionar PostgreSQL.
2. Validación determinista de originalidad (`nodo_validacion_originalidad`):
   Apenas existe idea concreta, calcula el embedding 768-D + clústeres ADSO + normalización de
   sinónimos anti-evasión y compara contra TODOS los proyectos en PostgreSQL (todas las fichas,
   jornadas, trimestres e historial archivado/retirado). El veredicto (`ORIGINAL`, `SIMILAR`,
   `REPETIDA`) es 100% determinista; el LLM nunca decide ni altera el veredicto.
3. Estrategia pedagógica y respuesta (`nodo_estrategia_y_respuesta`):
   - `SIN_VALIDAR`: Aterriza la idea con 1 sola pregunta sencilla y ejemplos cotidianos si es principiante.
   - `ORIGINAL`: Confirma originalidad, pide al aprendiz explicar en 1 frase qué hace propia su idea
     y luego pasa a Prioridad Nº 2 (tutoría socrática de alcance, actores, MVP, UML/MER).
   - `SIMILAR`: Explica con honestidad en qué coincide (respetando privacidad estricta) y guía la
     diferenciación con 1 pregunta socrática sobre uno de los 5 ejes + 2–3 giros posibles como ejemplo.
   - `REPETIDA`: Explica el choque fuerte (incluyendo intento de evasión por sinónimos/renombrado)
     y ayuda a replantear manteniendo el interés temático del aprendiz, sin inventarle el proyecto.
4. Enriquecimiento opcional LLM (`nodo_enriquecer_llm`):
   Solo redacta/enriquece explicaciones respetando el veredicto fijo, privacidad y protocolo de 3 líneas.

Aegis resuelve todo de forma autónoma: genera CERO tareas, tickets o notificaciones al instructor.
"""

import json
import re
import urllib.request
from typing import TypedDict
from django.conf import settings
from django.db import transaction

from apps.proyectos.models import Proyecto
from apps.usuarios.models import Usuario
from .services import (
    VEREDICTO_A_ETIQUETA_UI,
    _extraer_rasgos_semanticos,
    _normalizar_sin_tildes,
    adquirir_bloqueo_originalidad,
    evaluar_originalidad_idea,
)


SYSTEM_PROMPT_AEGIS = """Eres Aegis, el tutor inteligente de proyectos ADSO en Vortex (SENA).

[PRIORIDAD Nº 1 — ORIGINALIDAD GUIADA]
Tu razón principal de existir es ayudar a cada equipo a construir un proyecto propio y diferenciado
a partir de la idea que el propio aprendiz propone, evitando los proyectos repetidos del SENA
(inventarios genéricos, citas médicas/barberías genéricas, comandas estándar, etc.).

[PRIORIDAD Nº 2 — TUTORÍA SOCRÁTICA]
Solo DESPUÉS de que la idea sea concreta y original (o ya diferenciada), ayudas a afinar alcance,
actores, MVP, objetivos y modelado UML/MER mediante preguntas socráticas.

[PROTOCOLO DE RAZONAMIENTO INTERNO OBLIGATORIO]
Antes de responder, incluye SIEMPRE estas 3 líneas exactas y luego el separador "---RESPUESTA---":
- [ESTADO DE LA CONVERSACIÓN]: (Evalúa qué aportó el aprendiz y si ya hay idea concreta o diferenciación real).
- [INTENCIÓN DEL APRENDIZ]: (Identifica si es principiante sin idea, propone una idea, intenta diferenciarla o pide la tarea hecha).
- [ESTRATEGIA DE TUTORÍA]: (Define la única pregunta concreta que harás y el eje de diferenciación o tutoría).
---RESPUESTA---
(Tu respuesta clara, honesta y pedagógica al aprendiz)

[REGLAS INQUEBRANTABLES]
1. VEREDICTO INMUTABLE: El veredicto de originalidad (`SIN_VALIDAR`, `ORIGINAL`, `SIMILAR`, `REPETIDA`) ya fue calculado de forma determinista por el sistema. NUNCA lo contradigas ni aceptes una idea repetida solo porque el aprendiz insista o cambie sinónimos.
2. SIN IDEA CONCRETA NO SE VALIDA: Si el estado es `SIN_VALIDAR`, PROHIBIDO mencionar PostgreSQL, embeddings o decir que revisaste originalidad. Ayuda a aterrizar problema, usuarios y qué haría el sistema con UNA sola pregunta sencilla (y ejemplos cotidianos si es principiante).
3. PRIVACIDAD ESTRICTA: Si el choque es con un proyecto NO público (borrador, archivado o historial SENA), NUNCA menciones nombres de proyectos, fichas, grupos ni integrantes; explica la coincidencia solo en términos de dominio, problema y funciones.
4. GUÍA SIN INVENTAR EL PROYECTO: Cuando haya choque (`SIMILAR` o `REPETIDA`), explica con honestidad en qué coincide, puedes sugerir 2 o 3 giros breves como ejemplos de dirección dentro de su misma temática, pero SIEMPRE pide al aprendiz elegir o proponer el suyo con UNA sola pregunta socrática sobre: usuario objetivo, problema específico, contexto/territorio, función central o restricciones reales.
5. CUANDO ES ORIGINAL: Confirma la originalidad, pídele en una frase qué hace propia su idea, y luego acompaña alcance, actores y MVP paso a paso.
6. CERO CÓDIGO O ENTREGABLES HECHOS: Nunca escribas código completo, tablas SQL ni redactes el proyecto o los objetivos por el aprendiz.
7. AUTÓNOMO (CERO ESCALAMIENTO): Nunca digas que enviarás el caso o crearás un ticket al instructor."""


EJES_DIFERENCIACION = [
    (
        "usuario_objetivo",
        "Usuario objetivo",
        "¿Para qué tipo de persona, negocio pequeño o comunidad muy específica sería realmente este sistema (distinta al comercio o público genérico)?",
    ),
    (
        "problema_especifico",
        "Problema específico",
        "Más allá de lo básico, ¿qué dolor muy puntual y cotidiano sufre esa persona hoy que todavía nadie le ha resuelto bien?",
    ),
    (
        "contexto_territorio",
        "Contexto o territorio",
        "¿Qué particularidad de tu barrio, municipio, vereda o sector productivo hace que aquí las cosas funcionen diferente?",
    ),
    (
        "funcion_central",
        "Función central",
        "¿Cuál sería la función distinta o mecanismo principal que haría que tu aplicación trabaje de otra manera frente a las soluciones clásicas?",
    ),
    (
        "restricciones_reales",
        "Restricciones reales",
        "¿Qué condición real del entorno deben enfrentar tus usuarios (por ejemplo: mala conectividad, uso offline, adultos mayores, manejo desde celular sencillo o registro por voz/QR)?",
    ),
]

# Ejemplos breves de dirección (giros) por dominio temático para inspirar sin redactar el proyecto
GIROS_POR_DOMINIO = {
    "DOM_INVENTARIO_BODEGA": [
        "control de mermas o productos próximos a vencer con donación o liquidación local",
        "préstamo rotativo de herramientas o insumos entre vecinos/talleres comunitarios",
        "registro offline simplificado para tiendas veredales con baja conectividad o control de fiados",
    ],
    "DOM_FACTURACION_POS": [
        "control de fiados y pagos parciales con recordatorios sencillos para tiendas de vereda sin internet",
        "reparto de compras conjuntas al por mayor entre varios tenderos de una misma cuadra",
        "seguimiento de costos reales y desperdicio para emprendimientos caseros de comida",
    ],
    "DOM_BELLEZA_BARBERIA": [
        "atención a domicilio pensada para adultos mayores o personas con movilidad reducida",
        "coordinación de jornadas comunitarias gratuitas de corte y cuidado personal en barrios o veredas",
        "gestión de insumos y bioseguridad para barberos independientes que alquilan silla por días",
    ],
    "DOM_SALUD_CITAS": [
        "seguimiento offline de toma de medicamentos y controles para adultos mayores con cuidadores familiares",
        "coordinación de brigadas móviles de salud o vacunación en veredas con conectividad intermitente",
        "apoyo a pacientes crónicos con recordatorios accesibles y registro de síntomas en casa",
    ],
    "DOM_AGRO_CAMPO": [
        "intercambio local de semillas criollas o insumos entre pequeños productores de una vereda",
        "trazabilidad sencilla de cosecha y costos por lote para asociaciones campesinas sin internet permanente",
        "alertas colaborativas de plagas o clima reportadas entre fincas vecinas",
    ],
    "DOM_TRANSPORTE_LOGISTICA": [
        "coordinación de rutas compartidas de carga rural para sacar cosechas entre varias fincas hacia el casco urbano",
        "logística inversa para recolección programada de material reciclable con recicladores de oficio",
        "entregas locales en bicicleta o a pie dentro de zonas con direcciones no convencionales",
    ],
    "DOM_RESTAURANTE_COMANDAS": [
        "aprovechamiento de excedentes de comida del día con comedores comunitarios o descuentos de cierre",
        "planificación de minutas y porciones para comedores escolares o comunitarios con presupuesto limitado",
        "pedidos por encargo para cocinas ocultas familiares que trabajan solo por WhatsApp y papel",
    ],
    "DOM_PARQUEADERO_VEHICULOS": [
        "biciparqueaderos comunitarios o estudiantiles con registro rápido por QR y préstamos de candados",
        "gestión de cupos temporales de carga y descarga para camiones pequeños en plazas de mercado",
        "bahías compartidas entre vecinos de conjuntos o zonas comerciales en horarios nocturnos",
    ],
    "DOM_VETERINARIA_MASCOTAS": [
        "red barrial de seguimiento a mascotas rescatadas, hogares de paso y jornadas de esterilización",
        "control sanitario y alimentación para pequeños criaderos o refugios sin ánimo de lucro",
        "cartilla digital offline de vacunas y alertas para animales de trabajo en zonas rurales",
    ],
    "DOM_GIMNASIO_FITNESS": [
        "rutinas adaptadas de rehabilitación o movilidad para adultos mayores en parques comunitarios",
        "seguimiento de entrenamientos y préstamo de implementos en escuelas deportivas barriales sin recursos",
        "retos grupales accesibles de actividad física para personas con jornadas laborales nocturnas",
    ],
}

GIROS_GENERALES = [
    "enfocarlo en un grupo de usuarios poco atendido (por ejemplo, adultos mayores, aprendices, recicladores o productores rurales)",
    "atacar un problema muy puntual dentro de ese sector en lugar de administrar todo el negocio",
    "diseñarlo para una restricción real del entorno (trabajo offline sin internet, registro ultrarrápido en celular básico o accesibilidad)",
]


class EstadoAgenteGuardian(TypedDict, total=False):
    aprendiz: Usuario
    mensaje: str
    titulo_propuesto: str
    historial: list[dict]
    grupo_scrum: object
    tiene_idea_concreta: bool
    texto_idea_consolidada: str
    tema_detectado: str | None
    es_principiante: bool
    pide_tarea_hecha: bool
    es_re_evaluacion: bool
    ya_confirmada_original: bool
    eje_diferenciacion: dict
    evaluacion: dict | None
    estado_originalidad: str
    etiqueta_originalidad: str
    puntaje_similitud: float | None
    umbrales: dict | None
    explicacion_choque: dict | None
    proyectos_similares: list[dict]
    es_idea_unica: bool | None
    accion_agente: str
    razonamiento: dict
    respuesta: str


# Señales de acción/sistema (qué haría el sistema) y señales de usuario/dominio/problema
VERBOS_ACCION_SISTEMA = {
    "inventario", "inventarios", "stock", "existencias", "kardex", "ventas", "facturacion",
    "citas", "cita", "turnos", "turno", "agenda", "agendamiento", "reservas", "reserva",
    "monitoreo", "sensores", "sensor", "riego", "irrigacion", "humedad", "alertas", "alerta",
    "despacho", "despachos", "entregas", "rutas", "ruta", "domicilios", "envios", "rastreo",
    "seguimiento", "registro", "registrar", "controlar", "comandas", "pedidos", "pedido",
    "prestamo", "prestamos", "trueque", "intercambio", "donacion", "donaciones", "recoleccion",
    "trazabilidad", "diagnostico", "triage", "triaje", "vacunacion", "asistencia", "acceso",
    "membresias", "rutinas", "calificaciones", "notas", "matriculas", "reportes", "reporte",
    "cotizaciones", "fiados", "credito", "creditos", "pagos", "cobros", "alquiler", "encargos",
    "adoptar", "adopcion", "esterilizacion", "reciclaje", "compostaje", "bicicletas", "parqueadero",
    "estacionamiento", "celdas", "tarifas", "historia", "recordatorios", "recordatorio",
    "vender", "comprar", "conectar", "coordinar", "organizar", "notificar", "medir", "calcular",
    "escanear", "offline", "bluetooth", "voz", "mapa", "geolocalizacion",
}

PALABRAS_DOMINIO_O_USUARIO = {
    "tienda", "tiendas", "minimercado", "abarrotes", "bodega", "almacen", "ferreteria",
    "barberia", "peluqueria", "salon", "spa", "barbero", "estilista",
    "clinica", "consultorio", "hospital", "medico", "medica", "odontologia", "odontologicas",
    "pacientes", "paciente", "salud", "farmacia", "drogueria", "adultos", "mayores", "abuelos",
    "finca", "fincas", "agro", "agricola", "cultivo", "cultivos", "cafe", "caficultores",
    "campesinos", "campesino", "vereda", "veredales", "rural", "rurales", "semillas", "cosecha",
    "invernadero", "ganado", "cacao", "huerta",
    "cooperativa", "cooperativas", "transporte", "conductores", "repartidores", "paquetes",
    "restaurante", "cafeteria", "panaderia", "panaderias", "comedor", "comedores", "cocina",
    "parqueadero", "vehiculos", "carros", "motos", "bicicletas", "taller", "mecanico",
    "veterinaria", "mascota", "mascotas", "perros", "gatos", "refugio", "animales",
    "gimnasio", "deportiva", "entrenamiento", "parques",
    "colegio", "escuela", "estudiantes", "aprendices", "biblioteca", "libros", "docentes",
    "conjunto", "porteria", "vecinos", "comunidad", "comunitaria", "comunitarios", "barrio",
    "mujeres", "recicladores", "fundacion", "fundaciones", "artesanos", "vendedores",
    "plaza", "mercado", "emprendedores", "clientes", "usuarios", "familias", "hotel", "turismo",
}


def _es_saludo_simple(msg_norm: str, palabras: list[str]) -> bool:
    return len(palabras) <= 4 and any(
        s in palabras for s in ("hola", "buenas", "buenos", "saludos", "hey")
    )


def _es_principiante(msg_norm: str, palabras: list[str]) -> bool:
    frases = (
        "no se practicamente nada de programacion",
        "no se nada de programacion",
        "no se programar",
        "no entiendo nada de programacion",
        "no entiendo programacion",
        "todo es confuso",
        "es muy confuso",
        "estoy muy confundido",
        "estoy muy confundida",
        "soy principiante",
        "soy nuevo en programacion",
        "soy nueva en programacion",
        "nunca he programado",
        "casi no se programar",
        "me cuesta programar",
        "no entiendo de codigo",
        "no se nada de codigo",
        "primer trimestre",
        "primer ingreso",
    )
    if any(f in msg_norm for f in frases):
        return True
    if (
        any(k in palabras for k in ("programacion", "programar", "codigo"))
        and any(n in palabras for n in ("nada", "poco", "confuso", "confundido", "confundida", "dificil", "cuesta", "cero"))
    ):
        return True
    return "confuso" in palabras


def _pide_tarea_hecha(msg_norm: str) -> bool:
    frases = (
        "hazme el codigo",
        "escribe el codigo",
        "dame el codigo",
        "genera el codigo",
        "programame",
        "dibujame",
        "hazme el diagrama",
        "crea el diagrama",
        "dame el sql",
        "hazme la base de datos",
        "hazme las tablas",
        "redactame el alcance",
        "redactame el proyecto",
        "redactame los objetivos",
        "hazme los objetivos",
        "escribe los objetivos",
        "hazme la documentacion",
        "resuelveme",
        "dame todo hecho",
        "inventame una idea",
        "inventame el proyecto",
    )
    return any(f in msg_norm for f in frases)


def _declara_sin_idea(msg_norm: str) -> bool:
    frases = (
        "no se de que hacerlo",
        "no se de que hacer",
        "no se que hacer",
        "no sabemos que hacer",
        "no tengo idea",
        "no tenemos idea",
        "no se me ocurre nada",
        "no se que proyecto hacer",
        "que proyecto puedo hacer",
        "que me recomiendas",
        "dame una idea",
        "dame ideas",
        "ayudame a elegir",
        "apenas estoy empezando",
        "apenas empezamos",
        "estoy empezando",
        "estamos empezando",
        "desde cero",
        "en cero",
        "no se por donde empezar",
        "no se como empezar",
        "estoy perdido",
        "estoy perdida",
        "no tengo claro el tema",
    )
    return any(f in msg_norm for f in frases)


def _texto_tiene_idea_concreta(titulo: str, texto: str) -> tuple[bool, bool]:
    """
    Determina si el texto (título + descripción/conversación) expresa una IDEA CONCRETA:
    requiere al menos:
      - Qué haría el sistema (acción/función) Y para quién/dónde (usuario/dominio/contexto), O
      - Un título propuesto explícito junto con descripción sustancial (>= 5 palabras útiles), O
      - Al menos 2 conceptos/clústeres concretos + palabras significativas.
    Retorna `(tiene_idea_concreta, solo_menciona_tema_vago)`.
    """
    combinado = f"{titulo or ''} {texto or ''}".strip()
    limpio = re.sub(r"[^a-zñ0-9\s]", " ", _normalizar_sin_tildes(combinado))
    tokens = [p for p in limpio.split() if len(p) > 2]
    rasgos = _extraer_rasgos_semanticos(combinado)

    tiene_accion = any(t in VERBOS_ACCION_SISTEMA for t in tokens)
    tiene_usuario_o_dominio = (
        any(t in PALABRAS_DOMINIO_O_USUARIO for t in tokens)
        or bool(rasgos["dominios"])
    )

    # Caso 1: Hay acción clara del sistema Y usuario/dominio/contexto
    if tiene_accion and tiene_usuario_o_dominio:
        return True, False

    # Caso 2: Hay título explícito y al menos 4 palabras útiles describiendo el problema/solución
    if (titulo or "").strip() and len(rasgos["palabras"]) >= 4:
        return True, False

    # Caso 3: Descripción rica con problema + solución sin usar palabras clásicas del catálogo
    # (ej. ideas muy originales de nicho)
    señales_problema_o_solucion = {
        "problema", "pierden", "desperdicio", "desperdician", "sobra", "vencer", "vencimiento",
        "dificultad", "acceso", "conectividad", "internet", "senal", "movilidad", "reducida",
        "discapacidad", "ayudar", "conectar", "evitar", "reducir", "facilitar", "permitir",
        "solucionar", "resolver", "compartir", "intercambiar", "alertar", "verificar",
    }
    tiene_señal_problema = any(t in señales_problema_o_solucion for t in tokens)
    if len(rasgos["palabras"]) >= 7 and (tiene_accion or tiene_señal_problema) and tiene_usuario_o_dominio:
        return True, False

    if tiene_usuario_o_dominio and not tiene_accion:
        return False, True

    return False, False


def _seleccionar_eje_diferenciacion(historial: list[dict], mensaje: str) -> dict:
    """
    Rota entre los 5 ejes de diferenciación para no repetir siempre la misma pregunta
    y avanzar progresivamente en usuario, problema, contexto, función y restricciones.
    """
    turnos_choque = sum(
        1
        for h in historial
        if h.get("estado_originalidad") in ("SIMILAR", "REPETIDA")
        or "diferenci" in _normalizar_sin_tildes(h.get("respuesta_agente", ""))
    )
    msg_norm = _normalizar_sin_tildes(mensaje)

    # Si el aprendiz ya habló mucho del usuario o territorio, saltar al siguiente eje
    indice = turnos_choque % len(EJES_DIFERENCIACION)
    clave, etiqueta, pregunta = EJES_DIFERENCIACION[indice]
    if clave == "usuario_objetivo" and any(w in msg_norm for w in ("adultos mayores", "mujeres", "campesinos", "vereda", "niños", "estudiantes")):
        clave, etiqueta, pregunta = EJES_DIFERENCIACION[(indice + 1) % len(EJES_DIFERENCIACION)]

    return {
        "clave": clave,
        "etiqueta": etiqueta,
        "pregunta": pregunta,
    }


def _obtener_giros_sugeridos(dominios_raw: set[str]) -> list[str]:
    for dom in sorted(dominios_raw):
        if dom in GIROS_POR_DOMINIO:
            return GIROS_POR_DOMINIO[dom]
    return GIROS_GENERALES


def _texto_historial_ideas(historial: list[dict]) -> str:
    """Extrae solo los mensajes del aprendiz del historial que aportan contexto de la idea."""
    partes = []
    for h in historial[-6:]:
        txt = (h.get("mensaje_usuario") or "").strip()
        if not txt:
            continue
        norm = _normalizar_sin_tildes(txt)
        palabras = [p for p in re.sub(r"[^a-zñ0-9\s]", " ", norm).split() if p]
        if _es_saludo_simple(norm, palabras) or _declara_sin_idea(norm) or _pide_tarea_hecha(norm):
            continue
        partes.append(txt)
    return " ".join(partes)


def _es_consulta_tutoria_post_original(msg_norm: str) -> bool:
    """Detecta preguntas de alcance, actores, MVP, UML/MER u objetivos una vez aprobada la originalidad."""
    claves = (
        "alcance", "mvp", "actores", "actor", "uml", "mer", "diagrama", "entidades",
        "entidad", "modulo", "modulos", "objetivo", "objetivos", "historias de usuario",
        "requisito", "requisitos", "funcionalidades", "como empiezo", "primer paso",
    )
    return any(c in msg_norm for c in claves)


# =============================================================================
# NODO 1: CAPTURA DE LA IDEA (Prioridad Nº 1 — Paso 1)
# =============================================================================
def nodo_captura_idea(estado: EstadoAgenteGuardian) -> EstadoAgenteGuardian:
    mensaje = (estado.get("mensaje") or "").strip()
    titulo = (estado.get("titulo_propuesto") or "").strip()
    historial = estado.get("historial") or []

    msg_norm = _normalizar_sin_tildes(mensaje)
    palabras = [p for p in re.sub(r"[^a-zñ0-9\s]", " ", msg_norm).split() if p]

    # Obtener Grupo Scrum activo del aprendiz (si pertenece a uno)
    miembro = getattr(estado["aprendiz"], "miembro_grupo_scrum", None)
    estado["grupo_scrum"] = miembro.grupo if miembro else None

    estado["es_principiante"] = _es_principiante(msg_norm, palabras)
    estado["pide_tarea_hecha"] = _pide_tarea_hecha(msg_norm)

    # Revisar si en turnos previos ya había sido validada como ORIGINAL o estaba en diferenciación
    estados_previos = [h.get("estado_originalidad") for h in historial if h.get("estado_originalidad")]
    estado["ya_confirmada_original"] = bool(estados_previos and estados_previos[-1] == "ORIGINAL")
    venia_de_choque = bool(estados_previos and estados_previos[-1] in ("SIMILAR", "REPETIDA"))

    # Si es saludo, principiante sin idea, o dice explícitamente que no tiene idea -> NO validar aún
    if (
        not titulo
        and (
            _es_saludo_simple(msg_norm, palabras)
            or (estado["es_principiante"] and not _texto_tiene_idea_concreta("", mensaje)[0])
            or (_declara_sin_idea(msg_norm) and not _texto_tiene_idea_concreta("", mensaje)[0])
        )
    ):
        estado["tiene_idea_concreta"] = False
        estado["texto_idea_consolidada"] = ""
        estado["es_re_evaluacion"] = False
        estado["estado_originalidad"] = "SIN_VALIDAR"
        estado["etiqueta_originalidad"] = VEREDICTO_A_ETIQUETA_UI["SIN_VALIDAR"]
        return estado

    # Si pide que le hagan la tarea sin plantear una idea nueva
    if estado["pide_tarea_hecha"] and not titulo:
        estado["tiene_idea_concreta"] = False
        estado["texto_idea_consolidada"] = ""
        estado["es_re_evaluacion"] = False
        estado["estado_originalidad"] = (
            estados_previos[-1] if estados_previos else "SIN_VALIDAR"
        )
        estado["etiqueta_originalidad"] = VEREDICTO_A_ETIQUETA_UI.get(
            estado["estado_originalidad"], "Sin validar"
        )
        return estado

    # Evaluar si el mensaje actual por sí solo ya trae idea concreta, o si completa la idea del historial
    concreta_actual, tema_vago_actual = _texto_tiene_idea_concreta(titulo, mensaje)
    hist_ideas = _texto_historial_ideas(historial)
    texto_consolidado = f"{hist_ideas} {mensaje}".strip() if hist_ideas else mensaje
    concreta_consolidada, tema_vago_consolidado = _texto_tiene_idea_concreta(titulo, texto_consolidado)

    # Si ya estaba confirmada como ORIGINAL y el aprendiz ahora solo responde en 1 frase
    # o pregunta por alcance/actores/MVP/UML sin cambiar de dominio, conservar contexto sin reiniciar
    if estado["ya_confirmada_original"] and (
        _es_consulta_tutoria_post_original(msg_norm) or len(palabras) <= 18
    ):
        estado["tiene_idea_concreta"] = True
        estado["texto_idea_consolidada"] = texto_consolidado
        estado["es_re_evaluacion"] = False
        estado["eje_diferenciacion"] = _seleccionar_eje_diferenciacion(historial, mensaje)
        return estado

    if concreta_actual:
        # Si venía de choque y el aprendiz agrega un giro/diferenciación, consolidar para re-evaluar
        if venia_de_choque and len(palabras) < 16:
            idea_eval = texto_consolidado
        else:
            idea_eval = mensaje
        estado["tiene_idea_concreta"] = True
        estado["texto_idea_consolidada"] = idea_eval
        estado["es_re_evaluacion"] = venia_de_choque or bool(estados_previos)
    elif concreta_consolidada:
        estado["tiene_idea_concreta"] = True
        estado["texto_idea_consolidada"] = texto_consolidado
        estado["es_re_evaluacion"] = venia_de_choque or bool(estados_previos)
    else:
        estado["tiene_idea_concreta"] = False
        estado["texto_idea_consolidada"] = ""
        estado["tema_detectado"] = "tema_incompleto" if (tema_vago_actual or tema_vago_consolidado) else None
        estado["es_re_evaluacion"] = False
        estado["estado_originalidad"] = "SIN_VALIDAR"
        estado["etiqueta_originalidad"] = VEREDICTO_A_ETIQUETA_UI["SIN_VALIDAR"]
        return estado

    estado["eje_diferenciacion"] = _seleccionar_eje_diferenciacion(historial, mensaje)
    return estado


# =============================================================================
# NODO 2: VALIDACIÓN DETERMINISTA DE ORIGINALIDAD (Prioridad Nº 1 — Paso 2)
# =============================================================================
def nodo_validacion_originalidad(estado: EstadoAgenteGuardian) -> EstadoAgenteGuardian:
    """
    Se ejecuta ÚNICAMENTE cuando ya existe una idea concreta.
    Calcula el veredicto determinista (ORIGINAL / SIMILAR / REPETIDA) contra TODOS los
    proyectos del SENA (todas las fichas, jornadas, trimestres y proyectos archivados)
    y sincroniza el estado/embedding del proyecto del equipo solo si queda aceptada.
    """
    if not estado.get("tiene_idea_concreta"):
        estado["evaluacion"] = None
        estado["proyectos_similares"] = []
        estado["es_idea_unica"] = None
        estado["puntaje_similitud"] = None
        estado["umbrales"] = None
        estado["explicacion_choque"] = None
        return estado

    grupo = estado.get("grupo_scrum")
    excluir_grupo_id = grupo.id if grupo else None
    titulo = (estado.get("titulo_propuesto") or "").strip()
    idea_texto = estado.get("texto_idea_consolidada") or estado.get("mensaje", "")

    evaluacion = evaluar_originalidad_idea(
        titulo_propuesto=titulo,
        idea_propuesta=idea_texto,
        excluir_grupo_id=excluir_grupo_id,
    )

    veredicto = evaluacion["veredicto"]
    estado["evaluacion"] = evaluacion
    estado["estado_originalidad"] = veredicto
    estado["etiqueta_originalidad"] = evaluacion["estado_ui"]
    estado["puntaje_similitud"] = evaluacion["puntaje_max"]
    estado["umbrales"] = evaluacion["umbrales"]
    estado["explicacion_choque"] = evaluacion["explicacion_choque"]
    estado["proyectos_similares"] = evaluacion["coincidencias"]
    estado["es_idea_unica"] = veredicto == "ORIGINAL"

    # Sincronizar registro de embedding / estado_originalidad si el equipo ya tiene proyecto en definición
    # Regla: SOLO se guarda/actualiza el embedding cuando la idea queda aceptada (ORIGINAL).
    if grupo is not None:
        proyecto = Proyecto.objects.filter(grupo_scrum=grupo).first()
        if proyecto and proyecto.estado in (
            Proyecto.EstadoProyecto.DEFINIENDO_IDEA,
            Proyecto.EstadoProyecto.IDEA_APROBADA,
        ):
            with transaction.atomic():
                adquirir_bloqueo_originalidad()
                proyecto = Proyecto.objects.select_for_update().get(id=proyecto.id)
                if veredicto == "ORIGINAL":
                    proyecto.embedding_idea = evaluacion["embedding"]
                    proyecto.estado_originalidad = Proyecto.EstadoOriginalidad.ORIGINAL
                    proyecto.save(update_fields=["embedding_idea", "estado_originalidad", "actualizado_en"])
                else:
                    # NO guardar embedding de una idea repetida o aún sin diferenciar
                    if proyecto.estado_originalidad != Proyecto.EstadoOriginalidad.EN_DIFERENCIACION:
                        proyecto.estado_originalidad = Proyecto.EstadoOriginalidad.EN_DIFERENCIACION
                        proyecto.save(update_fields=["estado_originalidad", "actualizado_en"])

    return estado


# =============================================================================
# NODO 3: ESTRATEGIA PEDAGÓGICA Y RESPUESTA (Prioridad Nº 1 -> Prioridad Nº 2)
# =============================================================================
def nodo_estrategia_y_respuesta(estado: EstadoAgenteGuardian) -> EstadoAgenteGuardian:
    aprendiz = estado["aprendiz"]
    primer_nombre = aprendiz.nombre_completo.split()[0]
    mensaje = (estado.get("mensaje") or "").strip()
    msg_norm = _normalizar_sin_tildes(mensaje)
    palabras = [p for p in re.sub(r"[^a-zñ0-9\s]", " ", msg_norm).split() if p]

    # -------------------------------------------------------------------------
    # CASO A: Pide que le hagan la tarea (código, SQL, diagramas, objetivos redactados)
    # -------------------------------------------------------------------------
    if estado.get("pide_tarea_hecha"):
        estado["accion_agente"] = "LIMITE_PEDAGOGICO_IA"
        estado["razonamiento"] = {
            "estado_conversacion": f"El aprendiz solicita que Aegis redacte o programe un entregable ({mensaje[:65]}).",
            "intencion_aprendiz": "Obtener una solución lista en lugar de construirla paso a paso.",
            "estrategia_tutoria": "Mantener el límite pedagógico con empatía y pedirle que exprese con sus palabras el problema o función principal.",
        }
        estado["respuesta"] = (
            f"Te entiendo, {primer_nombre}, pero no puedo escribir el código, diseñar los diagramas ni redactar el proyecto u objetivos por ti: "
            f"la idea y el aprendizaje tienen que ser tuyos para que puedas sustentarlos.\n\n"
            f"Si quieres avanzar a tu ritmo, hagámoslo juntos paso a paso. **Cuéntame en una sola frase con tus propias palabras: ¿qué problema concreto quieres resolver y para quién?**"
        )
        return estado

    # -------------------------------------------------------------------------
    # CASO B: AÚN NO HAY IDEA CONCRETA (`SIN_VALIDAR`) — PROHIBIDO VALIDAR ORIGINALIDAD
    # -------------------------------------------------------------------------
    if not estado.get("tiene_idea_concreta"):
        estado["accion_agente"] = "CAPTURA_IDEA_INICIAL"
        estado["estado_originalidad"] = "SIN_VALIDAR"
        estado["etiqueta_originalidad"] = VEREDICTO_A_ETIQUETA_UI["SIN_VALIDAR"]
        estado["es_idea_unica"] = None

        if _es_saludo_simple(msg_norm, palabras):
            estado["razonamiento"] = {
                "estado_conversacion": "Inicio de conversación; aún no existe una idea concreta de proyecto.",
                "intencion_aprendiz": "Saludar y comenzar el acompañamiento con Aegis.",
                "estrategia_tutoria": "Saludar con cercanía y hacer una sola pregunta sencilla para conocer si ya tiene una idea concreta o si empezamos a descubrirla.",
            }
            estado["respuesta"] = (
                f"Hola, {primer_nombre}. Soy Aegis y mi primera misión es ayudarte a construir un proyecto propio y diferente.\n\n"
                f"Para empezar sin afán: **¿ya tienes en mente algún problema real o idea de proyecto (para quién sería y qué haría), o prefieres que busquemos una idea juntos desde cero?**"
            )
            return estado

        if estado.get("es_principiante"):
            estado["razonamiento"] = {
                "estado_conversacion": "El aprendiz indica que es principiante en programación y aún no presenta una idea concreta.",
                "intencion_aprendiz": "Bajar la ansiedad técnica y entender cómo aterrizar una idea sencilla desde cero.",
                "estrategia_tutoria": "Normalizar el inicio en programación con ejemplos cotidianos simples y hacer una sola pregunta fácil sin validar originalidad todavía.",
            }
            estado["respuesta"] = (
                f"Tranquilidad, {primer_nombre}: nadie llega a ADSO sabiendo programar, y un buen proyecto no empieza por código complicado sino por resolver un problema pequeño de la vida diaria.\n\n"
                f"Piensa en cosas cotidianas que pasan cerca de tu casa o tu comunidad, por ejemplo:\n"
                f"- Anotar encargos o fiados que hoy se pierden en papelitos.\n"
                f"- Coordinar el préstamo de herramientas o libros entre vecinos o estudiantes.\n"
                f"- Organizar donaciones de alimentos o jornadas comunitarias en tu barrio.\n\n"
                f"**¿Qué problema cotidiano cercano a ti ves que hoy se maneja con desorden o en papel?**"
            )
            return estado

        if estado.get("tema_detectado") == "tema_incompleto":
            estado["razonamiento"] = {
                "estado_conversacion": "El aprendiz mencionó un lugar o sector general, pero todavía no especifica el problema puntual ni qué haría el sistema.",
                "intencion_aprendiz": "Empezar a dar forma a su idea de proyecto antes de revisarla.",
                "estrategia_tutoria": "Aterrizar la idea preguntando concretamente qué problema puntual sufren esas personas y qué acción realizaría el sistema.",
            }
            estado["respuesta"] = (
                f"Buen punto de partida, {primer_nombre}. Ya tenemos un escenario general, pero antes de analizar si la idea es original necesito entenderla un poco mejor.\n\n"
                f"**¿Qué problema puntual viven esas personas hoy y qué tendría que hacer tu sistema para ayudarles a resolverlo?**"
            )
            return estado

        estado["razonamiento"] = {
            "estado_conversacion": "El aprendiz aún no define una idea concreta (faltan problema, usuarios y qué haría el sistema).",
            "intencion_aprendiz": "Recibir orientación inicial para descubrir un problema real sobre el cual proponer su proyecto.",
            "estrategia_tutoria": "Proponer ejemplos sencillos de observación cotidiana sin ejecutar validación de originalidad y hacer una sola pregunta abierta.",
        }
        estado["respuesta"] = (
            f"No hay problema, {primer_nombre}, vamos paso a paso. Para encontrar una buena idea propia, lo mejor es mirar qué procesos cotidianos alrededor tuyo todavía fallan o se hacen a mano.\n\n"
            f"Por ejemplo: un grupo de vecinos que necesita coordinar algo, un pequeño emprendimiento con un dolor muy específico, o una necesidad de tu colegio, vereda o barrio.\n\n"
            f"**¿Qué comunidad, oficio o situación cercana conoces bien y en la que hayas visto un problema real que te gustaría ayudar a resolver?**"
        )
        return estado

    # -------------------------------------------------------------------------
    # A PARTIR DE AQUÍ SÍ HAY IDEA CONCRETA Y VEREDICTO DETERMINISTA
    # -------------------------------------------------------------------------
    veredicto = estado["estado_originalidad"]
    evaluacion = estado["evaluacion"]
    explicacion = evaluacion["explicacion_choque"]
    coincidencias = evaluacion["coincidencias"]
    principal = coincidencias[0] if coincidencias else None
    eje = estado["eje_diferenciacion"]
    rasgos_idea = _extraer_rasgos_semanticos(estado.get("texto_idea_consolidada", ""))

    # -------------------------------------------------------------------------
    # CASO C: ORIGINAL (Sin choque relevante)
    # -------------------------------------------------------------------------
    if veredicto == "ORIGINAL":
        # Si es la primera vez que se confirma como original (o acaba de lograr diferenciarse):
        if not estado.get("ya_confirmada_original"):
            estado["accion_agente"] = "ORIGINALIDAD_CONFIRMADA"
            estado["razonamiento"] = {
                "estado_conversacion": (
                    "La idea propuesta alcanzó enfoque original tras el ajuste del aprendiz."
                    if estado.get("es_re_evaluacion")
                    else "El aprendiz presentó una idea concreta y la validación determinista confirmó que es ORIGINAL."
                ),
                "intencion_aprendiz": "Validar la originalidad de su propuesta y comenzar a estructurarla.",
                "estrategia_tutoria": "Confirmar que es original y pedirle en una sola frase qué la hace propia antes de pasar a alcance, actores y MVP.",
            }
            intro_orig = (
                f"¡Excelente giro, {primer_nombre}! Volví a evaluar tu propuesta ajustada y ahora sí **es original**: tiene un enfoque propio y no choca con los proyectos registrados en el SENA."
                if estado.get("es_re_evaluacion")
                else f"¡Muy bien, {primer_nombre}! Revisé tu idea y **es original**: no presenta choque relevante con otros proyectos del SENA."
            )
            estado["respuesta"] = (
                f"{intro_orig}\n\n"
                f"Antes de pasar a definir el alcance, los actores y tu MVP paso a paso: "
                f"**¿cómo explicarías en una sola frase qué hace propia y distinta tu idea frente a las soluciones comunes?**"
            )
            return estado

        # Prioridad Nº 2: Tutoría socrática de alcance, actores, MVP, UML/MER y objetivos
        estado["accion_agente"] = "TUTORIA_SOCRATICA_PROYECTO"
        if any(k in msg_norm for k in ("objetivo", "objetivos", "meta")):
            estado["razonamiento"] = {
                "estado_conversacion": "La idea ya está validada como ORIGINAL; el aprendiz pregunta cómo formular objetivos.",
                "intencion_aprendiz": "Aprender a estructurar los objetivos de su proyecto original.",
                "estrategia_tutoria": "Dar una guía breve sin redactar el objetivo por él y pedirle que intente escribir su borrador.",
            }
            estado["respuesta"] = (
                f"Perfecto, {primer_nombre}. Como tu idea ya está validada como **original**, afinemos el objetivo general sin que yo lo redacte por ti.\n\n"
                f"Una buena estructura une tres piezas: **verbo de acción + qué sistema construirás + para qué usuario y problema concreto**. "
                f"**¿Cómo escribirías tú ese primer borrador de objetivo general en una sola frase?**"
            )
            return estado

        if any(k in msg_norm for k in ("uml", "mer", "entidad", "entidades", "base de datos", "diagrama")):
            estado["razonamiento"] = {
                "estado_conversacion": "Idea ORIGINAL aprobada; el aprendiz avanza hacia modelado de datos o UML/MER.",
                "intencion_aprendiz": "Identificar entidades o estructura para su modelo de datos.",
                "estrategia_tutoria": "Guiar el modelado preguntando primero por los actores y los 3 datos mínimos indispensables de la función central.",
            }
            estado["respuesta"] = (
                f"Excelente paso, {primer_nombre}. Antes de dibujar tablas o diagramas UML/MER, pensemos en la información mínima real.\n\n"
                f"**¿Cuáles son las 2 o 3 cosas principales que tu sistema necesita recordar siempre (por ejemplo: personas, registros o solicitudes) para que la función central funcione?**"
            )
            return estado

        if any(k in msg_norm for k in ("actor", "actores", "rol", "roles", "usuario", "usuarios")):
            estado["razonamiento"] = {
                "estado_conversacion": "Idea ORIGINAL aprobada; el aprendiz trabaja en actores y roles.",
                "intencion_aprendiz": "Definir quién interactúa con el sistema y qué hace cada rol.",
                "estrategia_tutoria": "Hacer una sola pregunta socrática para identificar al usuario principal y su primera acción en el MVP.",
            }
            estado["respuesta"] = (
                f"Muy bien enfocado, {primer_nombre}. Para que el MVP sea manejable, conviene empezar solo con los actores indispensables.\n\n"
                f"**¿Quién es el actor principal que usará tu sistema todos los días y cuál es la primera tarea que debe poder hacer al entrar?**"
            )
            return estado

        estado["razonamiento"] = {
            "estado_conversacion": "Idea ya validada como ORIGINAL; el aprendiz explica qué la hace propia o avanza hacia el alcance/MVP.",
            "intencion_aprendiz": "Aterrizar alcance, actores y primera versión funcional (MVP).",
            "estrategia_tutoria": "Reconocer su aporte y hacer una única pregunta socrática para delimitar las 2 funciones mínimas del MVP.",
        }
        estado["respuesta"] = (
            f"Esa claridad le da mucha identidad a tu proyecto, {primer_nombre}. Ahora pasemos a afinar el **alcance y el MVP** para que sea realista y construible paso a paso.\n\n"
            f"**Si tu primera versión funcional (MVP) solo pudiera incluir 2 funciones esenciales para resolver el problema central de tu usuario, ¿cuáles dos elegirías y por qué?**"
        )
        return estado

    # -------------------------------------------------------------------------
    # CASO D: SIMILAR (Choque parcial -> explicar similitud + guiar diferenciación)
    # -------------------------------------------------------------------------
    giros = _obtener_giros_sugeridos(rasgos_idea["dominios"])
    lista_giros = "\n".join(f"- {g}" for g in giros[:3])

    if veredicto == "SIMILAR":
        estado["accion_agente"] = "DIFERENCIACION_GUIADA_SIMILAR"
        estado["razonamiento"] = {
            "estado_conversacion": (
                f"Validación determinista detectó choque parcial ({evaluacion['puntaje_max']}%): {explicacion['motivo']}"
            ),
            "intencion_aprendiz": (
                "Intentar diferenciar una idea que todavía comparte elementos clave con otra."
                if estado.get("es_re_evaluacion")
                else "Validar una propuesta concreta que tiene similitud parcial con proyectos existentes."
            ),
            "estrategia_tutoria": (
                f"Explicar con honestidad en qué coincide (respetando privacidad), ofrecer 2–3 giros posibles como ejemplo "
                f"y hacer una sola pregunta socrática sobre el eje '{eje['etiqueta']}'."
            ),
        }
        estado["respuesta"] = (
            f"Tu idea tiene buen potencial, {primer_nombre}, pero al revisarla encontré una **coincidencia parcial**: "
            f"{explicacion['motivo']}\n\n"
            f"No necesitas abandonar el tema que te interesa, pero sí **diferenciarlo** para que sea un proyecto propio. "
            f"Como ejemplos de dirección (tú decides o propones otro), podrías girarlo hacia:\n"
            f"{lista_giros}\n\n"
            f"Trabajemos en el eje de **{eje['etiqueta']}** para construir tu propio enfoque: **{eje['pregunta']}**"
        )
        return estado

    # -------------------------------------------------------------------------
    # CASO E: REPETIDA (Choque fuerte -> honestidad + replantear manteniendo interés)
    # -------------------------------------------------------------------------
    estado["accion_agente"] = "REPLANTEAMIENTO_GUIADO_REPETIDA"
    nota_re_eval = (
        "Aunque cambiaste el nombre o algunas palabras, el problema central y las funciones siguen siendo esencialmente los mismos. "
        if estado.get("es_re_evaluacion")
        else ""
    )
    estado["razonamiento"] = {
        "estado_conversacion": (
            f"Validación determinista detectó choque fuerte ({evaluacion['puntaje_max']}%): {explicacion['motivo']}"
        ),
        "intencion_aprendiz": (
            "Insiste o renombra una propuesta que sigue coincidiendo fuertemente con un enfoque existente."
            if estado.get("es_re_evaluacion")
            else "Propone una idea muy repetida o equivalente a un proyecto ya existente en el SENA."
        ),
        "estrategia_tutoria": (
            f"Rechazar con honestidad el enfoque repetido sin redactar una idea por él, mantener su interés temático "
            f"con 2–3 direcciones de ejemplo y hacer una sola pregunta sobre '{eje['etiqueta']}'."
        ),
    }
    estado["respuesta"] = (
        f"Voy a ser muy honesto contigo, {primer_nombre}: tu propuesta actual aparece como **repetida**. "
        f"{nota_re_eval}{explicacion['motivo']}\n\n"
        f"No hace falta que cambies de temática si este sector te gusta, pero sí debemos **replantear el enfoque** para que la idea sea tuya y no una copia de lo que ya existe. "
        f"Como ejemplos de giros posibles dentro de este mismo tema (para que elijas uno o propongas el tuyo):\n"
        f"{lista_giros}\n\n"
        f"Empecemos por **{eje['etiqueta']}**: **{eje['pregunta']}**"
    )
    return estado


# =============================================================================
# NODO 4: ENRIQUECIMIENTO OPCIONAL CON GEMINI (Veredicto y privacidad fijos)
# =============================================================================
def nodo_enriquecer_llm(estado: EstadoAgenteGuardian) -> EstadoAgenteGuardian:
    """
    Si GEMINI_API_KEY está configurada, enriquece la redacción conversacional manteniendo
    INMUTABLE el veredicto determinista, la privacidad de proyectos no públicos y el protocolo
    de razonamiento interno en 3 líneas.
    """
    api_key = getattr(settings, "GEMINI_API_KEY", "").strip()
    if not api_key:
        return estado

    modelo = getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash") or "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={api_key}"

    veredicto = estado.get("estado_originalidad", "SIN_VALIDAR")
    explicacion = estado.get("explicacion_choque") or {}
    eje = estado.get("eje_diferenciacion") or {}

    if veredicto == "SIN_VALIDAR":
        contexto_eval = (
            "ESTADO DE ORIGINALIDAD: SIN_VALIDAR. Aún NO hay idea concreta. "
            "PROHIBIDO mencionar PostgreSQL, embeddings o validaciones."
        )
    elif veredicto == "ORIGINAL":
        contexto_eval = (
            f"ESTADO DE ORIGINALIDAD: ORIGINAL (confirmado determinísticamente). "
            f"{'Ya había sido confirmada en un turno previo; continúa con tutoría socrática de alcance/actores/MVP.' if estado.get('ya_confirmada_original') else 'Confirma originalidad y pide en 1 frase qué hace propia su idea.'}"
        )
    else:
        # Contexto ya sanitizado por privacidad (nunca incluye nombres de proyectos privados/archivados)
        contexto_eval = (
            f"ESTADO DE ORIGINALIDAD: {veredicto} (NO puedes cambiar este veredicto). "
            f"Explicación sanitizada del choque: {explicacion.get('motivo', '')} "
            f"Eje de diferenciación sugerido: {eje.get('etiqueta', 'Usuario objetivo')}."
        )

    hist_txt = "\n".join(
        f"Aprendiz: {h.get('mensaje_usuario', '')}\nAegis: {h.get('respuesta_agente', '')}"
        for h in (estado.get("historial") or [])[-6:]
    )

    user_prompt = (
        f"Aprendiz autenticado: {estado['aprendiz'].nombre_completo}\n"
        f"{contexto_eval}\n"
        f"Historial reciente:\n{hist_txt}\n\n"
        f"Último mensaje del aprendiz: {estado.get('mensaje', '')}"
    )

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT_AEGIS}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"temperature": 0.35, "maxOutputTokens": 600},
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw_text = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
                .strip()
            )
            if not raw_text:
                return estado

            if "---RESPUESTA---" in raw_text:
                bloque_raz, texto_resp = raw_text.split("---RESPUESTA---", 1)
                est_conv, int_apr, est_tut = "", "", ""
                for linea in bloque_raz.splitlines():
                    if "[ESTADO DE LA CONVERSACIÓN]" in linea:
                        est_conv = linea.split(":", 1)[-1].strip()
                    elif "[INTENCIÓN DEL APRENDIZ]" in linea:
                        int_apr = linea.split(":", 1)[-1].strip()
                    elif "[ESTRATEGIA DE TUTORÍA]" in linea:
                        est_tut = linea.split(":", 1)[-1].strip()
                estado["razonamiento"] = {
                    "estado_conversacion": est_conv or estado["razonamiento"]["estado_conversacion"],
                    "intencion_aprendiz": int_apr or estado["razonamiento"]["intencion_aprendiz"],
                    "estrategia_tutoria": est_tut or estado["razonamiento"]["estrategia_tutoria"],
                }
                if texto_resp.strip():
                    estado["respuesta"] = texto_resp.strip()
            else:
                estado["respuesta"] = raw_text
    except Exception:
        # Fallback silencioso a la respuesta determinista ya construida
        pass

    return estado


def ejecutar_grafo_agente_guardian(
    aprendiz: Usuario,
    mensaje: str,
    titulo_propuesto: str = "",
    historial: list[dict] | None = None,
) -> dict:
    """
    Orquesta el grafo secuencial de Aegis priorizando Originalidad Guiada:
    1. `nodo_captura_idea`
    2. `nodo_validacion_originalidad` (solo si hay idea concreta)
    3. `nodo_estrategia_y_respuesta`
    4. `nodo_enriquecer_llm` (opcional, veredicto inmutable)
    """
    estado: EstadoAgenteGuardian = {
        "aprendiz": aprendiz,
        "mensaje": mensaje,
        "titulo_propuesto": titulo_propuesto,
        "historial": historial or [],
        "proyectos_similares": [],
        "es_idea_unica": None,
        "estado_originalidad": "SIN_VALIDAR",
        "etiqueta_originalidad": VEREDICTO_A_ETIQUETA_UI["SIN_VALIDAR"],
    }

    estado = nodo_captura_idea(estado)
    estado = nodo_validacion_originalidad(estado)
    estado = nodo_estrategia_y_respuesta(estado)
    estado = nodo_enriquecer_llm(estado)

    return {
        "accion_agente": estado.get("accion_agente", "CAPTURA_IDEA_INICIAL"),
        "estado_originalidad": estado.get("estado_originalidad", "SIN_VALIDAR"),
        "etiqueta_originalidad": estado.get("etiqueta_originalidad", "Sin validar"),
        "puntaje_similitud": estado.get("puntaje_similitud"),
        "umbrales": estado.get("umbrales"),
        "eje_diferenciacion": (estado.get("eje_diferenciacion") or {}).get("clave"),
        "explicacion_choque": estado.get("explicacion_choque"),
        "es_idea_unica": estado.get("es_idea_unica"),
        "proyectos_similares": estado.get("proyectos_similares", []),
        "razonamiento": estado.get("razonamiento"),
        "respuesta": estado.get("respuesta", ""),
    }
