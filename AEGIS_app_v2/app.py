import os
import sqlite3
from functools import wraps
from datetime import timedelta

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
    abort,
)
from werkzeug.utils import secure_filename


# =========================================================
# CONFIGURACIÓN
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "aegis.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")

os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)

app.config.update(
    SECRET_KEY=os.environ.get(
        "AEGIS_SECRET_KEY",
        "aegis-desarrollo-2026-clave-secreta"
    ),
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,

    # Configuración de sesión
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


# =========================================================
# BASE DE DATOS
# =========================================================

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = db()

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nickname TEXT NOT NULL UNIQUE,
            real_name TEXT DEFAULT '',
            photo TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            text TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            parent_id INTEGER DEFAULT NULL,
            text TEXT NOT NULL,
            likes INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(report_id)
                REFERENCES reports(id)
                ON DELETE CASCADE,

            FOREIGN KEY(user_id)
                REFERENCES users(id)
                ON DELETE CASCADE,

            FOREIGN KEY(parent_id)
                REFERENCES comments(id)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS comment_likes (
            comment_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,

            PRIMARY KEY(comment_id, user_id),

            FOREIGN KEY(comment_id)
                REFERENCES comments(id)
                ON DELETE CASCADE,

            FOREIGN KEY(user_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        );
    """)

    # Migración para bases de datos antiguas
    columns = [
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(users)"
        ).fetchall()
    ]

    if "displayed_level" not in columns:
        conn.execute("""
            ALTER TABLE users
            ADD COLUMN displayed_level TEXT DEFAULT ''
        """)

    conn.commit()
    conn.close()


# =========================================================
# USUARIO ACTUAL
# =========================================================

def current_user():
    uid = session.get("user_id")

    if not uid:
        return None

    conn = db()

    user = conn.execute(
        "SELECT * FROM users WHERE id=?",
        (uid,)
    ).fetchone()

    conn.close()

    # Si la sesión apunta a un usuario que ya no existe
    if user is None:
        session.pop("user_id", None)
        return None

    return user


# =========================================================
# AVATAR
# =========================================================

def avatar_for(photo):
    if photo:
        return photo

    return "default-avatar.svg"


# =========================================================
# NIVELES
# =========================================================

def level_for(user_id):
    conn = db()

    reports = conn.execute(
        "SELECT COUNT(*) FROM reports WHERE user_id=?",
        (user_id,)
    ).fetchone()[0]

    comments = conn.execute(
        "SELECT COUNT(*) FROM comments WHERE user_id=?",
        (user_id,)
    ).fetchone()[0]

    conn.close()

    activity = reports + comments

    if activity >= 50:
        return "AEGIS"

    if activity >= 20:
        return "Guardiana"

    if activity >= 5:
        return "Vigía"

    return "Novata"


def displayed_level_for(user_id):
    conn = db()

    row = conn.execute(
        "SELECT displayed_level FROM users WHERE id=?",
        (user_id,)
    ).fetchone()

    conn.close()

    if row and row["displayed_level"]:
        return row["displayed_level"]

    return level_for(user_id)


# =========================================================
# LOGIN REQUIRED
# =========================================================

def login_required(fn):

    @wraps(fn)
    def wrapper(*args, **kwargs):

        if not current_user():
            return jsonify({
                "error": "Debes crear tu perfil primero."
            }), 401

        return fn(*args, **kwargs)

    return wrapper


# =========================================================
# VARIABLES PARA TEMPLATES
# =========================================================

@app.context_processor
def inject_user():

    user = current_user()

    if user:
        return {
            "me": user,
            "my_level": level_for(user["id"])
        }

    return {
        "me": None,
        "my_level": None
    }


# =========================================================
# PÁGINA PRINCIPAL
# =========================================================

@app.route("/")
def index():

    user = current_user()

    if not user:
        return redirect(url_for("profile"))

    return render_template("index.html")


# =========================================================
# CREAR PERFIL
# =========================================================

@app.route("/profile", methods=["GET", "POST"])
def profile():

    # Si ya existe una sesión y entramos manualmente a /profile,
    # permitimos mostrar la página solo mediante GET.
    # Las ediciones posteriores se hacen desde /api/profile.

    if request.method == "POST":

        nickname = request.form.get(
            "nickname",
            ""
        ).strip()

        real_name = request.form.get(
            "real_name",
            ""
        ).strip()

        photo = request.files.get("photo")

        # -----------------------------
        # Validar nickname
        # -----------------------------

        if len(nickname) < 2 or len(nickname) > 24:

            return render_template(
                "profile.html",
                error="El apodo debe tener entre 2 y 24 caracteres."
            )

        conn = db()

        # -----------------------------
        # Verificar nickname repetido
        # -----------------------------

        exists = conn.execute(
            """
            SELECT id
            FROM users
            WHERE nickname=?
            """,
            (nickname,)
        ).fetchone()

        if exists:

            conn.close()

            return render_template(
                "profile.html",
                error="Ese apodo ya está ocupado."
            )

        # -----------------------------
        # Foto
        # -----------------------------

        photo_name = "default-avatar.svg"

        if photo and photo.filename:

            ext = (
                photo.filename.rsplit(".", 1)[-1].lower()
                if "." in photo.filename
                else ""
            )

            if ext not in ALLOWED_EXTENSIONS:

                conn.close()

                return render_template(
                    "profile.html",
                    error=(
                        "Foto no válida. "
                        "Usa PNG, JPG, JPEG o WEBP."
                    )
                )

            photo_name = (
                f"user_new_"
                f"{os.urandom(6).hex()}."
                f"{ext}"
            )

            photo.save(
                os.path.join(
                    UPLOAD_DIR,
                    secure_filename(photo_name)
                )
            )

        # -----------------------------
        # Crear usuario
        # -----------------------------

        cursor = conn.execute(
            """
            INSERT INTO users(
                nickname,
                real_name,
                photo,
                displayed_level
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                nickname,
                real_name,
                photo_name,
                "Novata"
            )
        )

        uid = cursor.lastrowid

        conn.commit()
        conn.close()

        # -----------------------------
        # CREAR SESIÓN
        # -----------------------------

        session.clear()

        session["user_id"] = int(uid)

        session.permanent = True

        # Marcar explícitamente la sesión como modificada
        session.modified = True

        # -----------------------------
        # Ir al mapa
        # -----------------------------

        return redirect(url_for("index"))

    return render_template("profile.html")


# =========================================================
# CREAR REPORTE
# =========================================================

@app.post("/api/reports")
@login_required
def create_report():

    data = request.get_json(
        silent=True
    ) or {}

    try:

        lat = float(data["lat"])
        lng = float(data["lng"])

    except (KeyError, TypeError, ValueError):

        return jsonify({
            "error": "Coordenadas inválidas."
        }), 400

    text = str(
        data.get("text", "")
    ).strip()

    if not text or len(text) > 500:

        return jsonify({
            "error":
                "El reporte debe tener entre 1 y 500 caracteres."
        }), 400

    if not (
        -90 <= lat <= 90
        and
        -180 <= lng <= 180
    ):

        return jsonify({
            "error": "Coordenadas fuera de rango."
        }), 400

    conn = db()

    cur = conn.execute(
        """
        INSERT INTO reports(
            user_id,
            lat,
            lng,
            text
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            session["user_id"],
            lat,
            lng,
            text
        )
    )

    report_id = cur.lastrowid

    conn.commit()

    row = conn.execute(
        """
        SELECT
            r.*,
            u.nickname,
            u.photo
        FROM reports r
        JOIN users u
            ON u.id = r.user_id
        WHERE r.id=?
        """,
        (report_id,)
    ).fetchone()

    conn.close()

    return jsonify({

        "id": row["id"],

        "lat": row["lat"],

        "lng": row["lng"],

        "text": row["text"],

        "nickname": row["nickname"],

        "photo": avatar_for(
            row["photo"]
        ),

        "level": displayed_level_for(
            row["user_id"]
        )

    }), 201


# =========================================================
# OBTENER REPORTES
# =========================================================

@app.get("/api/reports")
@login_required
def get_reports():

    conn = db()

    rows = conn.execute(
        """
        SELECT
            r.*,
            u.nickname,
            u.photo,
            u.id AS author_id

        FROM reports r

        JOIN users u
            ON u.id = r.user_id

        ORDER BY r.id ASC
        """
    ).fetchall()

    conn.close()

    result = []

    for r in rows:

        result.append({

            "id": r["id"],

            "lat": r["lat"],

            "lng": r["lng"],

            "text": r["text"],

            "nickname": r["nickname"],

            "photo": avatar_for(
                r["photo"]
            ),

            "level": displayed_level_for(
                r["author_id"]
            )

        })

    return jsonify(result)


# =========================================================
# OBTENER COMENTARIOS
# =========================================================

@app.get(
    "/api/reports/<int:report_id>/comments"
)
@login_required
def get_comments(report_id):

    conn = db()

    exists = conn.execute(
        """
        SELECT id
        FROM reports
        WHERE id=?
        """,
        (report_id,)
    ).fetchone()

    if not exists:

        conn.close()

        abort(404)

    rows = conn.execute(
        """
        SELECT
            c.*,
            u.nickname,
            u.photo,
            u.id AS author_id,

            EXISTS(
                SELECT 1
                FROM comment_likes cl
                WHERE
                    cl.comment_id=c.id
                    AND
                    cl.user_id=?
            ) AS liked

        FROM comments c

        JOIN users u
            ON u.id=c.user_id

        WHERE c.report_id=?

        ORDER BY c.id ASC
        """,
        (
            session["user_id"],
            report_id
        )
    ).fetchall()

    conn.close()

    result = []

    for r in rows:

        result.append({

            "id": r["id"],

            "parent_id": r["parent_id"],

            "text": r["text"],

            "likes": r["likes"],

            "liked": bool(
                r["liked"]
            ),

            "nickname": r["nickname"],

            "photo": avatar_for(
                r["photo"]
            ),

            "level": displayed_level_for(
                r["author_id"]
            ),

            "created_at": r["created_at"]

        })

    return jsonify(result)


# =========================================================
# CREAR COMENTARIO / RESPUESTA
# =========================================================

@app.post(
    "/api/reports/<int:report_id>/comments"
)
@login_required
def create_comment(report_id):

    data = request.get_json(
        silent=True
    ) or {}

    text = str(
        data.get("text", "")
    ).strip()

    parent_id = data.get(
        "parent_id"
    )

    if not text or len(text) > 1000:

        return jsonify({
            "error":
                "El comentario debe tener entre 1 y 1000 caracteres."
        }), 400

    conn = db()

    report_exists = conn.execute(
        """
        SELECT id
        FROM reports
        WHERE id=?
        """,
        (report_id,)
    ).fetchone()

    if not report_exists:

        conn.close()

        return jsonify({
            "error": "Reporte no encontrado."
        }), 404

    # -----------------------------
    # Respuesta a comentario
    # -----------------------------

    if parent_id is not None:

        try:

            parent_id = int(
                parent_id
            )

        except (TypeError, ValueError):

            conn.close()

            return jsonify({
                "error": "Respuesta inválida."
            }), 400

        parent = conn.execute(
            """
            SELECT id
            FROM comments
            WHERE
                id=?
                AND
                report_id=?
            """,
            (
                parent_id,
                report_id
            )
        ).fetchone()

        if not parent:

            conn.close()

            return jsonify({
                "error":
                    "El comentario padre no existe."
            }), 400

    cur = conn.execute(
        """
        INSERT INTO comments(
            report_id,
            user_id,
            parent_id,
            text
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            report_id,
            session["user_id"],
            parent_id,
            text
        )
    )

    conn.commit()

    cid = cur.lastrowid

    conn.close()

    return jsonify({
        "id": cid
    }), 201


# =========================================================
# LIKE COMENTARIO
# =========================================================

@app.post(
    "/api/comments/<int:comment_id>/like"
)
@login_required
def toggle_like(comment_id):

    conn = db()

    comment = conn.execute(
        """
        SELECT id
        FROM comments
        WHERE id=?
        """,
        (comment_id,)
    ).fetchone()

    if not comment:

        conn.close()

        return jsonify({
            "error":
                "Comentario no encontrado."
        }), 404

    existing = conn.execute(
        """
        SELECT 1
        FROM comment_likes
        WHERE
            comment_id=?
            AND
            user_id=?
        """,
        (
            comment_id,
            session["user_id"]
        )
    ).fetchone()

    if existing:

        conn.execute(
            """
            DELETE FROM comment_likes
            WHERE
                comment_id=?
                AND
                user_id=?
            """,
            (
                comment_id,
                session["user_id"]
            )
        )

        conn.execute(
            """
            UPDATE comments
            SET likes=MAX(likes-1, 0)
            WHERE id=?
            """,
            (comment_id,)
        )

        liked = False

    else:

        conn.execute(
            """
            INSERT INTO comment_likes(
                comment_id,
                user_id
            )
            VALUES (?, ?)
            """,
            (
                comment_id,
                session["user_id"]
            )
        )

        conn.execute(
            """
            UPDATE comments
            SET likes=likes+1
            WHERE id=?
            """,
            (comment_id,)
        )

        liked = True

    likes = conn.execute(
        """
        SELECT likes
        FROM comments
        WHERE id=?
        """,
        (comment_id,)
    ).fetchone()[0]

    conn.commit()
    conn.close()

    return jsonify({
        "liked": liked,
        "likes": likes
    })


# =========================================================
# INFORMACIÓN DEL USUARIO
# =========================================================

@app.get("/api/me")
@login_required
def me_api():

    user = current_user()

    real_level = level_for(
        user["id"]
    )

    displayed_level = (
        user["displayed_level"]
        or
        real_level
    )

    return jsonify({

        "id":
            user["id"],

        "nickname":
            user["nickname"],

        "real_name":
            user["real_name"],

        "photo":
            avatar_for(
                user["photo"]
            ),

        "level":
            real_level,

        "displayed_level":
            displayed_level

    })


# =========================================================
# EDITAR PERFIL
# =========================================================

@app.post("/api/profile")
@login_required
def update_profile():

    data = request.get_json(
        silent=True
    ) or {}

    nickname = str(
        data.get("nickname", "")
    ).strip()

    real_name = str(
        data.get("real_name", "")
    ).strip()

    displayed_level = str(
        data.get(
            "displayed_level",
            ""
        )
    ).strip()

    if (
        len(nickname) < 2
        or
        len(nickname) > 24
    ):

        return jsonify({
            "error":
                "El apodo debe tener entre 2 y 24 caracteres."
        }), 400

    conn = db()

    exists = conn.execute(
        """
        SELECT id
        FROM users
        WHERE
            nickname=?
            AND
            id != ?
        """,
        (
            nickname,
            session["user_id"]
        )
    ).fetchone()

    if exists:

        conn.close()

        return jsonify({
            "error":
                "Ese apodo ya está ocupado."
        }), 400

    allowed = [
        "Novata",
        "Vigía",
        "Guardiana",
        "AEGIS"
    ]

    actual = level_for(
        session["user_id"]
    )

    actual_index = allowed.index(
        actual
    )

    if displayed_level in allowed:

        requested = displayed_level

    else:

        requested = actual

    if (
        allowed.index(requested)
        >
        actual_index
    ):

        requested = actual

    conn.execute(
        """
        UPDATE users
        SET
            nickname=?,
            real_name=?,
            displayed_level=?
        WHERE id=?
        """,
        (
            nickname,
            real_name,
            requested,
            session["user_id"]
        )
    )

    conn.commit()
    conn.close()

    return jsonify({

        "ok": True,

        "nickname":
            nickname,

        "real_level":
            actual,

        "displayed_level":
            requested

    })


# =========================================================
# CAMBIAR FOTO
# =========================================================

@app.post("/api/profile/photo")
@login_required
def update_profile_photo():

    photo = request.files.get(
        "photo"
    )

    if not photo or not photo.filename:

        return jsonify({
            "error":
                "No se recibió ninguna foto."
        }), 400

    ext = (
        photo.filename.rsplit(
            ".",
            1
        )[-1].lower()
        if "." in photo.filename
        else ""
    )

    if ext not in ALLOWED_EXTENSIONS:

        return jsonify({
            "error":
                "Foto no válida. "
                "Usa PNG, JPG, JPEG o WEBP."
        }), 400

    photo_name = (
        f"user_"
        f"{session['user_id']}_"
        f"{os.urandom(6).hex()}."
        f"{ext}"
    )

    photo.save(
        os.path.join(
            UPLOAD_DIR,
            secure_filename(
                photo_name
            )
        )
    )

    conn = db()

    conn.execute(
        """
        UPDATE users
        SET photo=?
        WHERE id=?
        """,
        (
            photo_name,
            session["user_id"]
        )
    )

    conn.commit()
    conn.close()

    return jsonify({

        "ok": True,

        "photo":
            photo_name

    })


# =========================================================
# CERRAR SESIÓN
# =========================================================

@app.post("/api/logout")
def logout():

    session.clear()

    return jsonify({
        "ok": True
    })


# =========================================================
# INICIAR BASE DE DATOS
# =========================================================

init_db()


# =========================================================
# EJECUTAR AEGIS
# =========================================================

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)