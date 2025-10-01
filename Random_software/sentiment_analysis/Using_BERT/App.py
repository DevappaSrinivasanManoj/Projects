from transformers import pipeline

classifier = pipeline("sentiment-analysis")

import pandas as pd

new_reviews = pd.Series([
    'This is wicked cool'
])


results = classifier(new_reviews.tolist())

for review, result in zip(new_reviews, results):
    print(f"\nReview: {review}\nPrediction: {result['label']}, Confidence: {result['score']:.2f}")