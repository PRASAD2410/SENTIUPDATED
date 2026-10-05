"""Load trained NER once; explicitly report rule-only fallback."""
import os
import spacy

MODEL_NAME = os.getenv('SPACY_MODEL', 'en_core_web_sm')
NLP_WARNING = None
try:
    NLP=spacy.load(MODEL_NAME)
    if 'ner' not in NLP.pipe_names:
        raise OSError('The configured pipeline has no trained NER component.')
except OSError:
    NLP=spacy.blank('en')
    NLP_WARNING = f'Trained spaCy model {MODEL_NAME} is unavailable. Only identifier rules and optional Gemini extraction are active. Install backend/requirements.txt.'

def nlp_status():
    return {'model': MODEL_NAME, 'nerReady': 'ner' in NLP.pipe_names,
            'warning': NLP_WARNING}
