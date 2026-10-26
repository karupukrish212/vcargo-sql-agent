"""Web chat UI: python app.py, then open http://<APP_HOST>:<APP_PORT>"""
import logging

from vanna.flask import VannaFlaskApp

import settings
from vanna_client import build_vanna

logging.basicConfig(level=logging.INFO)

vn = build_vanna()

app = VannaFlaskApp(
    vn,
    title=settings.APP_TITLE,
    subtitle="Ask questions about the business data in plain English.",
    debug=False,
    allow_llm_to_see_data=settings.ALLOW_LLM_TO_SEE_DATA,
    show_training_data=settings.SHOW_TRAINING_DATA,
    # Needs Vanna's hosted service, which this local setup doesn't use
    function_generation=False,
)

if __name__ == "__main__":
    app.run(host=settings.APP_HOST, port=settings.APP_PORT, debug=False)
