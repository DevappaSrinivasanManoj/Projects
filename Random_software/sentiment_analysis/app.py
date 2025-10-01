import pickle
import pandas as pd
from flask import Flask, request, jsonify

app = Flask(__name__)

# Load the model
with open('sentiment_model.pkl', 'rb') as f:
    loaded_tfidf, loaded_model = pickle.load(f)

@app.route('/predict', methods=['POST'])
def predict():
    data = request.get_json()
    if 'comments' not in data:
        return jsonify({'error': 'No comments provided'}), 400

    comments = data['comments']
    above_hundred = len(comments) > 100

    if above_hundred:
        comments = comments[:100]

    X_new = loaded_tfidf.transform(comments)
    predictions = loaded_model.predict(X_new)

    sentiments = [('positive' if pred == '__label__2' else 'negative') for pred in predictions]

    good_comments_count = sentiments.count('positive')
    percentage_good_comments = (good_comments_count / len(sentiments)) * 100 if sentiments else 0

    return jsonify({
        'sentiments': sentiments,
        'percentage_good_comments': percentage_good_comments,
        'aboveHundred': above_hundred
    })

