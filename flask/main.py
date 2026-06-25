from flask import Flask, render_template
from flask_sock import Sock


def create_app(test_config=None):
    app = Flask(__name__)
    sock = Sock(app)

    if test_config is not None:
        app.config.from_mapping(test_config)

    from collaboration import bp as collaboration_bp, register_socket
    from items import bp

    app.register_blueprint(bp)
    app.register_blueprint(collaboration_bp)
    register_socket(sock)

    @app.get("/")
    def read_root():
        return render_template("index.html")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
