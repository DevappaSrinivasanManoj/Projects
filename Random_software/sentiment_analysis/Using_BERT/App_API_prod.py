from flask import Flask, request, jsonify
from transformers import pipeline

app = Flask(__name__)

# Load the sentiment analysis pipeline
classifier = pipeline(
    "sentiment-analysis",
    model="distilbert-base-uncased-finetuned-sst-2-english",
    revision="main"  # or a specific commit hash
)

@app.route('/predict', methods=['POST'])
def predict():
    """
    Accepts a POST request with a JSON body containing a "texts" field,
    which should be an array of strings.
    Returns the sentiment for each string.
    """
    if not request.json or 'texts' not in request.json:
        return jsonify({'error': 'Missing "texts" key in request body'}), 400

    texts = request.json['texts']
    if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
        return jsonify({'error': '"texts" must be an array of strings'}), 400

    if len(texts) > 100:
        return jsonify({'error': 'The number of texts cannot exceed 100 per request'}), 400

    try:
        # The classifier can handle a list of strings directly and efficiently
        results = classifier(texts)
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
