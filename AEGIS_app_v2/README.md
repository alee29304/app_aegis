# AEGIS — MVP

Versión demo de AEGIS, mapa colaborativo de seguridad enfocado en San Ramón.

## Cambios de esta versión

- Inicio de perfil rediseñado en morado, blanco y negro.
- Avatar oficial AEGIS automático si no se sube una foto.
- Mapa centrado en San Ramón, con el área de navegación limitada a la zona de la comuna y sectores inmediatos.
- Barra superior con:
  - Mapa
  - Mi nivel
  - ¿Cómo funciona?
  - Perfil
- El botón del perfil ahora abre un panel de personalización y NO cierra la sesión.
- Se puede editar apodo, nombre real y foto.
- El rango mostrado puede seleccionarse entre los rangos ya alcanzados.
- Los rangos superiores permanecen bloqueados hasta alcanzarlos mediante actividad.
- Se mantiene el sistema de reportes, comentarios anidados y likes.

## Ejecutar

```bash
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
py app.py
```

Luego:

http://127.0.0.1:5000

## Nota sobre rangos

El nivel real continúa calculándose automáticamente según la actividad:
- Novata: 0–4
- Vigía: 5–19
- Guardiana: 20–49
- AEGIS: 50+

La selección del perfil no permite mostrar un rango que todavía no se haya alcanzado.
