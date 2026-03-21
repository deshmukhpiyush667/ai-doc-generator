from extensions import db

class Document(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, nullable=False)

    title = db.Column(db.String(200))

    content = db.Column(db.Text)

    created_at = db.Column(db.DateTime, server_default=db.func.now())