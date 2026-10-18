"""Ejemplos estáticos de estimaciones para el prompt."""
ESTIMATION_EXAMPLES = [
    {
        "meeting_summary": "El cliente necesita una plataforma web de gestión de inventario...",
        "estimation": """
        ## Estimación: Plataforma de Gestión de Inventario
        
        ### Desglose de tareas:
        1. Diseño UI/UX: 40 horas
        2. Backend API (CRUD inventario): 60 horas
        3. Autenticación y roles: 20 horas
        4. Dashboard con métricas: 30 horas
        5. Testing y QA: 25 horas
        
        **Total estimado: 175 horas**
        **Equipo recomendado: 2 desarrolladores full-stack + 1 diseñador UX (part-time)**
        **Duración estimada: 6-8 semanas**
        """
    },
    {
        "meeting_summary": (
            "El cliente necesita una plataforma web de reservas para una clínica. "
            "Los pacientes podrán registrarse, consultar la disponibilidad y reservar "
            "o cancelar citas. El personal gestionará las agendas de los profesionales "
            "y se enviarán confirmaciones y recordatorios por correo electrónico."
        ),
        "estimation": """
        ## Estimación: Plataforma de Reservas para Clínica

        ### Desglose de tareas:
        1. Diseño UI/UX: 35 horas
        2. Backend API (gestión de citas y disponibilidad): 65 horas
        3. Autenticación y roles (paciente y personal): 25 horas
        4. Calendario de reservas y panel de administración: 45 horas
        5. Confirmaciones y recordatorios por correo electrónico: 20 horas
        6. Testing y QA: 30 horas

        **Total estimado: 220 horas**
        **Equipo recomendado: 2 desarrolladores full-stack + 1 diseñador UX (part-time)**
        **Duración estimada: 6-8 semanas**
        """
    },
    {
        "meeting_summary": (
            "El cliente necesita una tienda online para vender productos artesanales. "
            "Los usuarios podrán consultar el catálogo, filtrar productos, añadirlos "
            "al carrito y pagar mediante una pasarela de pago. El administrador "
            "gestionará productos y pedidos, y los compradores recibirán "
            "confirmaciones por correo electrónico."
        ),
        "estimation": """
        ## Estimación: Tienda Online de Productos Artesanales

        ### Desglose de tareas:
        1. Diseño UI/UX: 40 horas
        2. Backend API (catálogo, productos y pedidos): 60 horas
        3. Autenticación y roles (cliente y administrador): 25 horas
        4. Catálogo con filtros y carrito de compra: 45 horas
        5. Integración con pasarela de pago: 30 horas
        6. Panel de administración: 30 horas
        7. Confirmaciones por correo electrónico: 15 horas
        8. Testing y QA: 35 horas

        **Total estimado: 280 horas**
        **Equipo recomendado: 2 desarrolladores full-stack + 1 diseñador UX (part-time)**
        **Duración estimada: 8-10 semanas**
        """
    },
]
