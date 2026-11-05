"""
Módulo 5: Motor de Razonamiento y Tutoría Académica de Aegis IA (apps/asistente/graph.py)

Eres Aegis, un tutor de ingeniería de software del SENA. Tu objetivo es guiar a aprendices
(como Laura Valentina) a estructurar el alcance y objetivos de sus proyectos desde cero,
paso a paso, fomentando el autoaprendizaje y evitando proyectos duplicados.

[PROTOCOLO DE RAZONAMIENTO OBLIGATORIO]
Antes de generar la respuesta final al usuario, ejecuta un bloque de análisis bajo el formato:
- [ESTADO DE LA CONVERSACIÓN]: Evalúa qué respondió el usuario en el último mensaje y si se sale del alcance anterior.
- [INTENCIÓN DEL APRENDIZ]: Identifica si está confundido, si apenas empieza, o si está pidiendo que le hagas la tarea.
- [ESTRATEGIA DE TUTORÍA]: Define qué pregunta clave harás para guiarlo sin darle la solución hecha.

[CORRECCIÓN CRÍTICA DE FLUJO]
1. PROHIBIDO VERIFICAR ORIGINALIDAD SI NO HAY IDEA:
   - NUNCA menciones que "revisaste en PostgreSQL" o que el proyecto "tiene vía libre por originalidad"
     a menos que el aprendiz YA HAYA ESPECIFICADO una idea concreta de negocio o proyecto (ej: barbería,
     veterinaria, tienda de ropa, tienda de barrio). Si no sabe de qué hacerlo, guíalo a proponer ideas.
2. ADAPTACIÓN AL NIVEL DE INICIO (PRINCIPIANTE):
   - Si manifiesta que es principiante ("no sé prácticamente nada de programación", "todo es confuso"),
     baja la exigencia técnica inmediata. Propón ejemplos de la vida real muy sencillos (ej: una libreta
     digital para apuntar pedidos de una tienda de barrio o una agenda de citas) y explícale que la
     programación se aprende resolviendo un problema chiquito a la vez.
3. UNA SOLA PREGUNTA SENCILLA:
   - Mantén las preguntas orientadoras aterrizadas al nivel de un aprendiz de primer ingreso.
"""

import json
import re
import urllib.request
from typing import TypedDict
from django.conf import settings

from apps.usuarios.models import Usuario
from .services import _normalizar_sin_tildes, buscar_proyectos_similares


SYSTEM_PROMPT_AEGIS = """Eres Aegis, un tutor de ingeniería de software del SENA. Tu objetivo es guiar a aprendices a estructurar el alcance y objetivos de sus proyectos desde cero, paso a paso, fomentando el autoaprendizaje y evitando proyectos duplicados.

[PROTOCOLO DE RAZONAMIENTO OBLIGATORIO]
Antes de tu respuesta, devuelve SIEMPRE un bloque de razonamiento exacto con estas 3 líneas y luego "---RESPUESTA---":
- [ESTADO DE LA CONVERSACIÓN]: (Evalúa qué respondió el usuario en el último mensaje y cómo conecta con lo anterior).
- [INTENCIÓN DEL APRENDIZ]: (Identifica si está confundido, si es principiante sin idea aún, si propone una idea o si pide que le hagas la tarea).
- [ESTRATEGIA DE TUTORÍA]: (Define la única pregunta sencilla que harás para guiarlo sin darle la solución hecha).
---RESPUESTA---
(Tu respuesta al aprendiz aquí)

[REGLAS CRÍTICAS DE COMPORTAMIENTO Y FLUJO]
1. PROHIBIDO VERIFICAR ORIGINALIDAD SI NO HAY IDEA: NUNCA menciones que "revisaste en PostgreSQL" o que el proyecto "tiene vía libre por originalidad" a menos que el aprendiz YA HAYA ESPECIFICADO una idea concreta de negocio o proyecto (ej: una barbería, una veterinaria, una tienda de ropa). Si dice que no sabe de qué hacerlo, guíalo a proponer ideas sencillas sin inventar validaciones vacías.
2. ADAPTACIÓN AL NIVEL DE INICIO (PRINCIPIANTE): Si el estudiante dice que es principiante ("no sé prácticamente nada de programación", "todo es confuso"), baja la exigencia técnica inmediata. No preguntes por modelos de datos complejos ni alertas avanzadas; proponle ejemplos cotidianos muy sencillos (ej: una libreta digital para apuntar pedidos de una tienda de barrio o una agenda sencilla de citas) y explícale que la programación se aprende resolviendo un problema chiquito a la vez.
3. PROHIBIDO USAR PLANTILLAS FIJAS: Nunca recicles frases armadas ni copies fragmentos literales de lo que dijo el usuario.
4. UNA SOLA PREGUNTA SENCILLA A LA VEZ: Mantén las preguntas orientadoras aterrizadas al nivel de un aprendiz de primer ingreso. No lo satures con arquitectura de software.
5. CERO CÓDIGO O TAREAS HECHAS: No escribas código ni redactes los objetivos por ellos."""


class EstadoAgenteGuardian(TypedDict, total=False):
    aprendiz: Usuario
    mensaje: str
    titulo_propuesto: str
    historial: list[dict]
    idea_concreta: str | None
    idea_recien_propuesta: bool
    intencion: str
    proyectos_similares: list[dict]
    es_idea_unica: bool | None
    accion_agente: str
    razonamiento: dict
    respuesta: str


# Catálogo de dominios / ideas concretas de negocio o proyecto
MAPA_IDEAS_CONCRETAS = [
    (("barberia", "barbero", "corte de cabello", "barba"), "una barbería"),
    (("peluqueria", "estilista", "salon de belleza", "spa", "uñas", "manicura"), "una peluquería o salón de belleza"),
    (("veterinaria", "mascota", "mascotas", "perro", "perros", "gato", "gatos", "vacunacion"), "una veterinaria"),
    (("tienda de ropa", "boutique", "ropa", "prendas", "camisetas", "calzado", "zapatos"), "una tienda de ropa o calzado"),
    (("tienda de barrio", "minimercado", "abarrotes", "miscelanea", "papeleria", "fiados", "tendero"), "una tienda de barrio"),
    (("panaderia", "pasteleria", "reposteria", "pan"), "una panadería o pastelería"),
    (("restaurante", "cafeteria", "comidas rapidas", "asadero", "pizzeria", "heladeria", "almuerzos"), "un negocio de comidas o cafetería"),
    (("ferreteria", "herramientas", "materiales de construccion"), "una ferretería"),
    (("parqueadero", "estacionamiento", "lavadero", "carros", "motos"), "un parqueadero o lavadero de vehículos"),
    (("taller mecanico", "taller de motos", "mecanica", "repuestos"), "un taller mecánico"),
    (("gimnasio", "entrenamiento", "crossfit", "cancha sintetica", "escuela deportiva"), "un gimnasio o espacio deportivo"),
    (("finca", "agro", "cultivo", "cosecha", "cacao", "cafe", "ganado", "galpon", "pollos", "invernadero"), "un proyecto para el campo o finca"),
    (("consultorio", "odontologia", "citas medicas", "pacientes", "drogueria", "farmacia", "optica"), "un consultorio o servicio de salud"),
    (("biblioteca", "prestamo de libros", "prestamo de equipos", "colegio", "jardin infantil", "notas escolares"), "un espacio educativo o de préstamos"),
    (("hotel", "hostal", "cabanas", "reservas turisticas"), "un hospedaje o servicio turístico"),
    (("conjunto residencial", "porteria", "visitantes", "administracion de conjunto"), "una portería o conjunto residencial"),
    (("libreta de pedidos", "apuntar pedidos", "encargos", "agenda de citas", "agenda de turnos", "gastos personales"), "un registro digital de pedidos o citas"),
]


def _extraer_idea_concreta(texto: str) -> str | None:
    """
    Devuelve la descripción natural de la idea SOLO si el texto menciona un negocio,
    sector o caso concreto real. Si el aprendiz no ha especificado ninguna idea, devuelve None.
    """
    t = _normalizar_sin_tildes(texto)
    for keywords, etiqueta in MAPA_IDEAS_CONCRETAS:
        for kw in keywords:
            # Coincidencia por palabra/frase completa para evitar falsos positivos
            if re.search(rf"\b{re.escape(kw)}\b", t):
                return etiqueta
    return None


def _detectar_estado_e_intencion(
    mensaje: str,
    historial: list[dict],
    idea_actual: str | None,
    idea_previa: str | None,
    similares: list[dict],
) -> str:
    """
    Clasifica la situación pedagógica real del aprendiz priorizando:
    1. Si es principiante / confundido con programación.
    2. Si aún no tiene idea de proyecto o empieza desde cero.
    3. Si pide que le hagan la tarea.
    4. Si acaba de proponer una idea concreta (solo ahí valida originalidad / diferencial).
    5. Continuidad paso a paso con preguntas sencillas.
    """
    msg = _normalizar_sin_tildes(mensaje).strip()
    palabras = [p for p in re.sub(r"[^a-zñ0-9\s]", " ", msg).split() if p]

    # 1. ¿Saludo inicial breve?
    if len(palabras) <= 4 and any(
        s in palabras for s in ("hola", "buenas", "buenos", "saludos", "hey", "que tal")
    ):
        return "SALUDO_INICIAL"

    # 2. ¿El estudiante manifiesta que es principiante en programación o que todo es confuso?
    frases_principiante_programacion = (
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
    if any(f in msg for f in frases_principiante_programacion) or (
        ("programacion" in palabras or "programar" in palabras or "codigo" in palabras)
        and any(n in palabras for n in ("nada", "poco", "confuso", "confundido", "confundida", "dificil", "cuesta", "cero"))
    ) or ("confuso" in palabras):
        return "PRINCIPIANTE_EN_PROGRAMACION"

    # 3. ¿El estudiante dice que NO tiene idea de qué proyecto hacer o pide ideas desde cero?
    frases_sin_idea = (
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
        "no entiendo",
    )
    if any(f in msg for f in frases_sin_idea):
        if idea_actual or idea_previa:
            return "PRINCIPIANTE_CON_IDEA_EN_MARCHA"
        return "SIN_IDEA_DE_PROYECTO"

    # 4. ¿Pide que le hagan la tarea (código, tablas SQL, diagramas o redacción de objetivos)?
    frases_facilitismo = (
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
        "hazme los objetivos",
        "escribe los objetivos por mi",
        "hazme la documentacion",
        "resuelveme",
        "dame todo hecho",
    )
    if any(f in msg for f in frases_facilitismo):
        return "SOLICITUD_DE_TAREA_HECHA"

    # 5. Si todavía NO hay ninguna idea concreta en el mensaje ni en el historial,
    #    PROHIBIDO verificar originalidad: guiar al aprendiz a proponer una idea sencilla.
    idea_activa = idea_actual or idea_previa
    if not idea_activa:
        return "SIN_IDEA_DE_PROYECTO"

    # 6. Si YA HAY una idea concreta y choca con un proyecto registrado en PostgreSQL:
    if similares:
        return "COLISION_CON_PROYECTO_EXISTENTE"

    # 7. Si el aprendiz ACABA de proponer por primera vez su idea concreta en este mensaje:
    if idea_actual and idea_actual != idea_previa:
        negocios_comunes = (
            "una barbería",
            "una peluquería o salón de belleza",
            "una ferretería",
            "un parqueadero o lavadero de vehículos",
            "un negocio de comidas o cafetería",
            "un gimnasio o espacio deportivo",
        )
        if idea_actual in negocios_comunes and len(palabras) <= 22:
            return "IDEA_COMUN_REQUIERE_ENFOQUE_SENCILLO"
        return "IDEA_CONCRETA_RECIEN_PROPUESTA"

    # 8. Si ya tenían la idea en marcha y el aprendiz está contando qué problema sencillo quiere resolver:
    if any(
        p in msg
        for p in (
            "problema", "pierden", "demora", "papel", "cuaderno", "libreta", "excel", "whatsapp",
            "manual", "desorden", "olvida", "cruzan", "error", "errores", "gasto", "anotar",
            "apuntar", "registrar", "pedidos", "citas", "turnos", "clientes", "ventas", "fiados",
        )
    ):
        return "ATERRIZANDO_PASO_A_PASO"

    # 9. Si pregunta por objetivos:
    if any(p in msg for p in ("objetivo", "objetivos", "meta", "lograr")):
        return "ESTRUCTURANDO_OBJETIVOS_SENCILLOS"

    # 10. Si pregunta por alcance o funciones:
    if any(p in msg for p in ("alcance", "modulo", "modulos", "funciones", "funcionalidades", "hacer primero")):
        return "ESTRUCTURANDO_ALCANCE_SENCILLO"

    # 11. Si el mensaje es breve ("sí", "listo", "me gusta la primera", "esa me sirve"):
    if len(palabras) <= 6:
        return "RESPUESTA_BREVE_CONTINUIDAD"

    return "ATERRIZANDO_PASO_A_PASO"


def _generar_razonamiento_y_respuesta_local(estado: EstadoAgenteGuardian) -> EstadoAgenteGuardian:
    aprendiz = estado["aprendiz"]
    primer_nombre = aprendiz.nombre_completo.split()[0]
    mensaje = (estado.get("mensaje") or "").strip()
    historial = estado.get("historial") or []
    similares = estado.get("proyectos_similares") or []

    idea_actual = estado.get("idea_concreta")
    textos_previos = " ".join(h.get("mensaje_usuario", "") for h in historial[-5:])
    idea_previa = _extraer_idea_concreta(textos_previos)
    idea_activa = idea_actual or idea_previa

    intencion = _detectar_estado_e_intencion(
        mensaje=mensaje,
        historial=historial,
        idea_actual=idea_actual,
        idea_previa=idea_previa,
        similares=similares,
    )
    estado["intencion"] = intencion

    # -------------------------------------------------------------------------
    # 1. SALUDO INICIAL (Sin mencionar validaciones hechas aún)
    # -------------------------------------------------------------------------
    if intencion == "SALUDO_INICIAL":
        estado["accion_agente"] = "ORIENTACION_INSTRUCTOR_IA"
        estado["es_idea_unica"] = None
        estado["razonamiento"] = {
            "estado_conversacion": "Inicio de la tutoría; el aprendiz saluda para abrir la conversación.",
            "intencion_aprendiz": "Recibir acompañamiento inicial para definir o revisar su proyecto.",
            "estrategia_tutoria": "Saludar con calidez y hacer una sola pregunta sencilla para saber si ya tiene una idea o si empezamos desde cero.",
        }
        estado["respuesta"] = (
            f"Hola, {primer_nombre}. Qué bueno saludarte.\n\n"
            f"Cuéntame con confianza para saber cómo acompañarte hoy: **¿ya tienes en mente alguna idea de negocio o problema para tu proyecto, o prefieres que empecemos desde cero buscando una idea sencilla?**"
        )
        return estado

    # -------------------------------------------------------------------------
    # 2. PRINCIPIANTE EN PROGRAMACIÓN ("no sé prácticamente nada de programación", "todo es confuso")
    # -------------------------------------------------------------------------
    if intencion == "PRINCIPIANTE_EN_PROGRAMACION":
        estado["accion_agente"] = "ORIENTACION_INSTRUCTOR_IA"
        estado["es_idea_unica"] = None
        estado["razonamiento"] = {
            "estado_conversacion": "El aprendiz expresa que está dando sus primeros pasos en programación y siente que los conceptos son confusos.",
            "intencion_aprendiz": "Necesita que el tutor baje la exigencia técnica, le quite el miedo a programar y lo guíe desde lo más básico.",
            "estrategia_tutoria": "Explicarle que programar se aprende resolviendo un problema pequeño a la vez, proponerle dos ejemplos cotidianos muy simples y preguntarle cuál le resulta más familiar.",
        }
        estado["respuesta"] = (
            f"Tranquila, {primer_nombre}, respira que nadie entra al SENA sabiendo programar y es normal que al principio todo suene confuso. La programación no se trata de memorizar cosas raras, sino de **resolver un problema chiquito a la vez**.\n\n"
            f"Olvídate por completo de términos complicados; pensemos en cosas sencillas de la vida diaria, por ejemplo:\n"
            f"- Una **libreta digital para apuntar los pedidos** de una tienda de barrio para que no se pierdan los papelitos.\n"
            f"- Una **agenda sencilla de citas** para anotar a qué hora llega cada cliente en una peluquería.\n\n"
            f"**¿Cuál de esos dos ejemplos sientes más fácil de imaginar en la vida real?**"
        )
        return estado

    # -------------------------------------------------------------------------
    # 3. SIN IDEA DE PROYECTO ("no sé de qué hacerlo", "apenas estoy empezando" sin tema aún)
    #    PROHIBIDO mencionar PostgreSQL u originalidad aquí.
    # -------------------------------------------------------------------------
    if intencion == "SIN_IDEA_DE_PROYECTO":
        estado["accion_agente"] = "ORIENTACION_INSTRUCTOR_IA"
        estado["es_idea_unica"] = None
        estado["razonamiento"] = {
            "estado_conversacion": "El aprendiz aún no tiene una idea concreta de proyecto definida.",
            "intencion_aprendiz": "Recibir orientación sencilla para descubrir un tema de proyecto cercano y fácil de entender.",
            "estrategia_tutoria": "Darle ejemplos cotidianos muy simples sin mencionar bases de datos ni originalidad todavía y hacerle una sola pregunta sencilla.",
        }
        estado["respuesta"] = (
            f"No te preocupes, {primer_nombre}, para eso estoy aquí. Cuando uno empieza desde cero, el mejor truco es mirar negocios pequeños cerca de casa que todavía apunten todo en un cuaderno.\n\n"
            f"Por ejemplo, podríamos pensar en algo tan sencillo como **una libreta digital para anotar encargos en una tienda de barrio**, **una agenda de turnos para una barbería o peluquería**, o **un control de préstamos de libros o implementos**.\n\n"
            f"**¿Alguno de esos tres te llama la atención, o conoces a alguien cerca de ti que tenga un pequeño negocio así?**"
        )
        return estado

    # -------------------------------------------------------------------------
    # 4. PRINCIPIANTE CON IDEA EN MARCHA (Ya eligió tema, pero no sabe cómo seguir)
    # -------------------------------------------------------------------------
    if intencion == "PRINCIPIANTE_CON_IDEA_EN_MARCHA":
        estado["accion_agente"] = "ORIENTACION_INSTRUCTOR_IA"
        estado["es_idea_unica"] = None
        estado["razonamiento"] = {
            "estado_conversacion": f"El aprendiz ya eligió trabajar sobre {idea_activa}, pero se siente inseguro sobre cómo estructurarlo.",
            "intencion_aprendiz": "Avanzar paso a paso con lenguaje cotidiano sin sentirse abrumado por tecnicismos.",
            "estrategia_tutoria": "Explicarle con un ejemplo cotidiano cómo dividir el problema en algo chiquito y hacerle una sola pregunta sencilla.",
        }
        estado["respuesta"] = (
            f"Vamos con calma, {primer_nombre}. Como la programación se aprende resolviendo un problema chiquito a la vez, no pensemos en hacer un programa gigante para {idea_activa}.\n\n"
            f"Imagina que solo vamos a reemplazar **una hoja de cuaderno** que ellos usen hoy todos los días: **¿qué es lo primero que el dueño o encargado anota hoy a mano en esa hoja cuando atiende a alguien?**"
        )
        return estado

    # -------------------------------------------------------------------------
    # 5. SOLICITUD DE TAREA HECHA (Cero facilitismo, adaptado con amabilidad)
    # -------------------------------------------------------------------------
    if intencion == "SOLICITUD_DE_TAREA_HECHA":
        estado["accion_agente"] = "LIMITE_PEDAGOGICO_IA"
        estado["es_idea_unica"] = None
        estado["razonamiento"] = {
            "estado_conversacion": f"El aprendiz pide que se le entregue resuelto un entregable ({mensaje[:55]}).",
            "intencion_aprendiz": "Obtener la redacción o el código listo porque posiblemente se siente bloqueado.",
            "estrategia_tutoria": "Explicarle con empatía por qué no debo hacerle la tarea y pedirle que me diga en una sola frase sencilla qué quiere lograr.",
        }
        estado["respuesta"] = (
            f"Te entiendo, {primer_nombre}, pero si yo te escribo el código o te redacto el trabajo, no vas a aprender cómo defenderlo cuando el instructor te pregunte. Mejor hagámoslo juntos paso a paso, que es mucho más fácil de lo que parece.\n\n"
            f"Si quieres ir mirando cómo funciona la web desde cero a tu ritmo, te recomiendo la [Guía para Principiantes de MDN](https://developer.mozilla.org/es/docs/Learn). Por ahora, cuéntame con tus propias palabras en una sola frase sencilla: **¿qué te gustaría que hiciera tu programa para ayudar a esa persona?**"
        )
        return estado

    # -------------------------------------------------------------------------
    # 6. COLISIÓN CON PROYECTO EXISTENTE EN POSTGRESQL (Solo porque YA HAY idea concreta)
    # -------------------------------------------------------------------------
    if intencion == "COLISION_CON_PROYECTO_EXISTENTE":
        principal = similares[0]
        estado["accion_agente"] = "ALERTA_PROYECTO_SIMILAR"
        estado["es_idea_unica"] = False
        estado["razonamiento"] = {
            "estado_conversacion": f"El aprendiz propone una idea concreta ({idea_activa}) que coincide en un {principal['similitud']}% con '{principal['titulo']}'.",
            "intencion_aprendiz": "Validar su idea de proyecto en el SENA.",
            "estrategia_tutoria": "Avisarle con claridad que ese enfoque ya está registrado por otro grupo y hacerle una pregunta sencilla para cambiarle el enfoque.",
        }
        estado["respuesta"] = (
            f"Acabo de revisar en PostgreSQL ahora que me contaste tu idea sobre {idea_activa}, y vi que ya existe un proyecto muy parecido (**{principal['similitud']}% de similitud**) llamado **{principal['titulo']}**, del **{principal['grupo_scrum']} (Ficha {principal['ficha']})**.\n\n"
            f"Para que tu proyecto sea único y sencillo de hacer: dentro de ese mismo negocio, **¿qué otra tarea pequeña (como apuntar encargos o controlar citas) te gustaría ayudarles a organizar?**"
        )
        return estado

    # -------------------------------------------------------------------------
    # 7. IDEA COMÚN RECIÉN PROPUESTA (Ya especificó negocio concreto, orientar de forma sencilla)
    # -------------------------------------------------------------------------
    if intencion == "IDEA_COMUN_REQUIERE_ENFOQUE_SENCILLO":
        estado["accion_agente"] = "IDEA_DISPONIBLE_Y_ORIGINAL"
        estado["es_idea_unica"] = True
        estado["razonamiento"] = {
            "estado_conversacion": f"El aprendiz acaba de proponer una idea concreta de negocio: {idea_activa}.",
            "intencion_aprendiz": "Empezar a dar forma a un proyecto sobre un negocio conocido.",
            "estrategia_tutoria": "Confirmar que revisamos su idea y hacerle una sola pregunta cotidiana y sencilla para elegir un problema pequeño que resolver ahí.",
        }
        estado["respuesta"] = (
            f"¡Muy buena elección para empezar, {primer_nombre}! Trabajar con **{idea_activa}** es genial porque es un negocio que uno conoce en la vida real, y revisando en PostgreSQL veo que podemos darle un enfoque propio sin chocar con otro grupo.\n\n"
            f"Como vamos a resolver un problema chiquito a la vez, piensa en algo muy sencillo: **¿qué te parece más útil resolverles primero: una agenda sencilla para que no se les crucen los turnos, o una libreta digital para anotar lo que gastan y venden en el día?**"
        )
        return estado

    # -------------------------------------------------------------------------
    # 8. IDEA CONCRETA RECIÉN PROPUESTA (Validación real en PostgreSQL porque YA hay idea)
    # -------------------------------------------------------------------------
    if intencion == "IDEA_CONCRETA_RECIEN_PROPUESTA":
        estado["accion_agente"] = "IDEA_DISPONIBLE_Y_ORIGINAL"
        estado["es_idea_unica"] = True
        estado["razonamiento"] = {
            "estado_conversacion": f"El aprendiz especifica por primera vez una idea concreta de proyecto: {idea_activa}.",
            "intencion_aprendiz": "Validar si su idea está disponible en el SENA y saber cuál es el primer paso para aterrizarla.",
            "estrategia_tutoria": "Confirmar la disponibilidad de la idea en PostgreSQL y hacerle una única pregunta sencilla sobre el problema cotidiano que quiere solucionar.",
        }
        estado["respuesta"] = (
            f"Me parece una excelente idea para empezar, {primer_nombre}. Ahora que tenemos un tema concreto (**{idea_activa}**), revisé en PostgreSQL y tienes vía libre porque ningún otro grupo tiene registrado ese enfoque.\n\n"
            f"Para ir armándolo pasito a pasito y sin complicarnos: **¿qué es lo que hoy hacen en papel o de memoria en {idea_activa} y que te gustaría pasar a una pantalla sencilla?**"
        )
        return estado

    # -------------------------------------------------------------------------
    # 9. ESTRUCTURANDO OBJETIVOS DE FORMA SENCILLA
    # -------------------------------------------------------------------------
    if intencion == "ESTRUCTURANDO_OBJETIVOS_SENCILLOS":
        estado["accion_agente"] = "ORIENTACION_INSTRUCTOR_IA"
        estado["es_idea_unica"] = True
        estado["razonamiento"] = {
            "estado_conversacion": f"El aprendiz quiere formular el objetivo de su proyecto para {idea_activa}.",
            "intencion_aprendiz": "Aprender cómo escribir un objetivo general claro sin enredarse.",
            "estrategia_tutoria": "Darle una fórmula muy fácil en lenguaje cotidiano y pedirle que intente escribir una frase sencilla.",
        }
        estado["respuesta"] = (
            f"Armar el objetivo general es más sencillo de lo que suena, {primer_nombre}. Solo tienes que unir tres ideas cortas en una sola frase: **¿Qué vas a crear? + ¿Para quién? + ¿Para ayudarle en qué tarea?**\n\n"
            f"Por ejemplo: *\"Crear una aplicación web sencilla para {idea_activa} que permita anotar...\"*. **¿Cómo terminarías tú esa frase con tus propias palabras?**"
        )
        return estado

    # -------------------------------------------------------------------------
    # 10. ESTRUCTURANDO ALCANCE DE FORMA SENCILLA
    # -------------------------------------------------------------------------
    if intencion == "ESTRUCTURANDO_ALCANCE_SENCILLO":
        estado["accion_agente"] = "ORIENTACION_INSTRUCTOR_IA"
        estado["es_idea_unica"] = True
        estado["razonamiento"] = {
            "estado_conversacion": f"El aprendiz consulta cómo definir el alcance para {idea_activa}.",
            "intencion_aprendiz": "Saber hasta dónde debe llegar su proyecto sin sobrecargarse.",
            "estrategia_tutoria": "Explicar el alcance como una lista pequeña de tareas que sí hará el programa y hacer una sola pregunta sencilla.",
        }
        estado["respuesta"] = (
            f"El \"alcance\" es simplemente acordar qué cositas pequeñas **sí** va a hacer tu programa para que no te quede gigante ni difícil de programar.\n\n"
            f"Pensando en {idea_activa}: **si tu programa solo tuviera dos botones principales para ayudar a la persona que atiende, ¿para qué serviría cada uno?**"
        )
        return estado

    # -------------------------------------------------------------------------
    # 11. RESPUESTA BREVE DE CONTINUIDAD
    # -------------------------------------------------------------------------
    if intencion == "RESPUESTA_BREVE_CONTINUIDAD":
        estado["accion_agente"] = "ORIENTACION_INSTRUCTOR_IA"
        estado["razonamiento"] = {
            "estado_conversacion": f"El aprendiz responde brevemente ('{mensaje}') sobre el trabajo que llevamos en {idea_activa}.",
            "intencion_aprendiz": "Continuar paso a paso con la guía del tutor.",
            "estrategia_tutoria": "Hacerle una única pregunta cotidiana sobre qué datos sencillos anotaría la persona en esa pantalla.",
        }
        estado["respuesta"] = (
            f"¡Listo, {primer_nombre}! Vamos súper bien con esa idea para {idea_activa}.\n\n"
            f"Imagina que ya tienes frente a ti esa libreta digital en la pantalla: **¿qué tres datos sencillos necesitarías escribir ahí cada vez que atiendas a una persona (por ejemplo: nombre, fecha y valor)?**"
        )
        return estado

    # -------------------------------------------------------------------------
    # 12. ATERRIZANDO PASO A PASO (Sin repetir validaciones de PostgreSQL)
    # -------------------------------------------------------------------------
    estado["accion_agente"] = "ORIENTACION_INSTRUCTOR_IA"
    estado["es_idea_unica"] = True
    estado["razonamiento"] = {
        "estado_conversacion": f"El aprendiz describe el problema cotidiano que quiere resolver en {idea_activa}.",
        "intencion_aprendiz": "Convertir esa necesidad de la vida real en una idea clara para su proyecto.",
        "estrategia_tutoria": "Validar lo claro de su ejemplo cotidiano y hacerle una sola pregunta sencilla sobre quién usará esa función.",
    }
    estado["respuesta"] = (
        f"¡Eso que acabas de describir es un excelente punto de partida, {primer_nombre}! Resolver algo tan concreto y real en {idea_activa} hace que el proyecto sea muy fácil de entender y de programar paso a paso.\n\n"
        f"Para dar el siguiente pasito: **¿quién sería la persona encargada de apuntar esa información en el programa todos los días (por ejemplo, el dueño del negocio o quien atiende en el mostrador)?**"
    )
    return estado


def _llamar_gemini_con_protocolo(estado: EstadoAgenteGuardian) -> dict | None:
    """
    Si GEMINI_API_KEY está configurada en settings/.env, invoca la API REST oficial de Google Gemini
    usando `urllib.request` nativo y extrae el bloque del [PROTOCOLO DE RAZONAMIENTO OBLIGATORIO].
    """
    api_key = getattr(settings, "GEMINI_API_KEY", "").strip()
    if not api_key:
        return None

    modelo = getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash") or "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={api_key}"

    idea_concreta = estado.get("idea_concreta")
    similares = estado.get("proyectos_similares") or []

    if not idea_concreta:
        contexto_bd = "EL APRENDIZ AÚN NO HA PROPUESTO UNA IDEA CONCRETA DE PROYECTO. PROHIBIDO mencionar PostgreSQL o decir que tiene vía libre por originalidad."
    elif similares:
        contexto_bd = f"COLISIÓN DETECTADA EN POSTGRESQL: Ya existe '{similares[0]['titulo']}' ({similares[0]['grupo_scrum']}, Ficha {similares[0]['ficha']}) con {similares[0]['similitud']}% de similitud."
    else:
        contexto_bd = f"IDEA CONCRETA DETECTADA ({idea_concreta}): Verificada en PostgreSQL sin proyectos duplicados."

    hist_txt = "\n".join(
        f"Aprendiz: {h.get('mensaje_usuario', '')}\nAegis: {h.get('respuesta_agente', '')}"
        for h in (estado.get("historial") or [])[-6:]
    )

    user_prompt = (
        f"Aprendiz autenticado: {estado['aprendiz'].nombre_completo}\n"
        f"Estado de idea y PostgreSQL: {contexto_bd}\n"
        f"Historial reciente:\n{hist_txt}\n\n"
        f"Último mensaje del aprendiz: {estado.get('mensaje', '')}"
    )

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT_AEGIS}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 600},
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
                return None

            if "---RESPUESTA---" in raw_text:
                partes = raw_text.split("---RESPUESTA---", 1)
                bloque_raz = partes[0].strip()
                texto_resp = partes[1].strip()
                est_conv, int_apr, est_tut = "", "", ""
                for linea in bloque_raz.splitlines():
                    if "[ESTADO DE LA CONVERSACIÓN]" in linea:
                        est_conv = linea.split(":", 1)[-1].strip()
                    elif "[INTENCIÓN DEL APRENDIZ]" in linea:
                        int_apr = linea.split(":", 1)[-1].strip()
                    elif "[ESTRATEGIA DE TUTORÍA]" in linea:
                        est_tut = linea.split(":", 1)[-1].strip()
                return {
                    "razonamiento": {
                        "estado_conversacion": est_conv or "Evaluación del mensaje actual del aprendiz.",
                        "intencion_aprendiz": int_apr or "Avanzar en la definición del proyecto.",
                        "estrategia_tutoria": est_tut or "Guiar con una pregunta sencilla paso a paso.",
                    },
                    "respuesta": texto_resp,
                }
            return {"razonamiento": None, "respuesta": raw_text}
    except Exception:
        return None


def ejecutar_grafo_agente_guardian(
    aprendiz: Usuario,
    mensaje: str,
    titulo_propuesto: str = "",
    historial: list[dict] | None = None,
) -> dict:
    historial_lista = historial or []
    idea_en_mensaje = _extraer_idea_concreta(f"{titulo_propuesto} {mensaje}")

    estado: EstadoAgenteGuardian = {
        "aprendiz": aprendiz,
        "mensaje": mensaje,
        "titulo_propuesto": titulo_propuesto,
        "historial": historial_lista,
        "idea_concreta": idea_en_mensaje,
        "proyectos_similares": [],
        "es_idea_unica": None,
    }

    # REGLA CRÍTICA 1: PROHIBIDO VERIFICAR ORIGINALIDAD SI NO HAY IDEA CONCRETA
    if idea_en_mensaje:
        estado["proyectos_similares"] = buscar_proyectos_similares(
            titulo_propuesto=titulo_propuesto or mensaje[:80],
            idea_propuesta=mensaje,
            excluir_grupo_id=None,
        )
        estado["es_idea_unica"] = len(estado["proyectos_similares"]) == 0

    # 2. Ejecutar protocolo de razonamiento y respuesta contextual adaptada al nivel del aprendiz
    estado = _generar_razonamiento_y_respuesta_local(estado)

    # 3. Si hay GEMINI_API_KEY configurada, enriquecer con Gemini respetando las reglas críticas
    res_gemini = _llamar_gemini_con_protocolo(estado)
    if res_gemini:
        if res_gemini.get("razonamiento"):
            estado["razonamiento"] = res_gemini["razonamiento"]
        estado["respuesta"] = res_gemini["respuesta"]

    return {
        "accion_agente": estado.get("accion_agente", "ORIENTACION_INSTRUCTOR_IA"),
        "es_idea_unica": estado.get("es_idea_unica"),
        "proyectos_similares": estado.get("proyectos_similares", []),
        "razonamiento": estado.get("razonamiento"),
        "respuesta": estado.get("respuesta", ""),
    }
