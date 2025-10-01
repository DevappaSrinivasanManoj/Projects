document.addEventListener('DOMContentLoaded', () => {
    const apiKeyInput = document.getElementById('api-key');
    const analyzeCommentBtn = document.getElementById('analyze-comment-btn');
    const commentInput = document.getElementById('comment-input');
    const commentResult = document.getElementById('comment-result');
    const analyzeCsvBtn = document.getElementById('analyze-csv-btn');
    const csvFileInput = document.getElementById('csv-file-input');
    const csvResult = document.getElementById('csv-result');

    const API_ENDPOINT = 'https://sentiment_analysis6.p.rapidapi.com/predict'; // Replace with your API endpoint
    const DEFAULT_API_KEY = '603ea374e3msh8fa1e5a3c9fc5acp13744fjsnd09208294e90'; // Replace with your default API key

    function localSentimentAnalysis(text) {
        const positiveWords = ['good', 'great', 'awesome', 'excellent', 'positive', 'happy', 'love', 'best', 'wonderful', 'like', 'nice', 'magnificent', 'cool'];
        const negativeWords = ['bad', 'terrible', 'awful', 'negative', 'sad', 'hate', 'worst', 'boring'];

        const words = text.toLowerCase().split(/\s+/);
        let score = 0;

        for (const word of words) {
            if (positiveWords.includes(word)) {
                score++;
            } else if (negativeWords.includes(word)) {
                score--;
            }
        }
        return { score };
    }

    analyzeCommentBtn.addEventListener('click', () => {
        const comment = commentInput.value.trim();
        if (!comment) {
            commentResult.textContent = 'Please enter a comment.';
            return;
        }

        const result = localSentimentAnalysis(comment);

        if (result.score === 0) { // Not confident
            analyzeCommentAPI(comment);
        } else {
            commentResult.textContent = `Sentiment: ${result.score > 0 ? 'Positive' : 'Negative'}`;
        }
    });

    analyzeCsvBtn.addEventListener('click', () => {
        const file = csvFileInput.files[0];
        if (!file) {
            csvResult.textContent = 'Please select a CSV file.';
            return;
        }

        Papa.parse(file, {
            complete: (results) => {
                const comments = results.data.slice(1).map(row => row[0]).filter(Boolean);
                if (comments.length > 0) {
                    analyzeCsvAPI(comments);
                }
            }
        });
    });

    function getApiKey() {
        return apiKeyInput.value.trim() || DEFAULT_API_KEY;
    }

    async function analyzeCommentAPI(comment) {
        const apiKey = getApiKey();
        try {
            const response = await fetch(API_ENDPOINT, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'x-rapidapi-key': apiKey
                },
                body: JSON.stringify({ comments: [comment] })
            });

            const data = await handleApiResponse(response);
            if (data && data.sentiments) {
                commentResult.textContent = `Sentiment: ${data.sentiments[0]}`;
            }
        } catch (error) {
            commentResult.textContent = error.message;
        }
    }

    async function analyzeCsvAPI(comments) {
        const apiKey = getApiKey();
        let commentsToSend = comments;
        if (comments.length > 100) {
            commentsToSend = comments.slice(0, 101);
        }

        try {
            const response = await fetch(API_ENDPOINT, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'x-rapidapi-key': apiKey
                },
                body: JSON.stringify({ comments: commentsToSend })
            });

            const data = await handleApiResponse(response);
            if (data) {
                let resultText = `Percentage of positive comments: ${data.percentage_good_comments}%`;
                if (data.aboveHundred) {
                    resultText += '\nWarning: Only the first 100 comments were analyzed as the API supports only 100 comments at a time.';
                }
                csvResult.textContent = resultText;
            }
        } catch (error) {
            csvResult.textContent = error.message;
        }
    }

    async function handleApiResponse(response) {
        const data = await response.json();
        if (!response.ok) {
            if (data.message && data.message.includes('exceeded the DAILY quota')) {
                throw new Error('You have exceeded the daily quota. Please use your own API key or upgrade the current plan.');
            } else {
                throw new Error(data.message || 'An error occurred.');
            }
        }
        return data;
    }
});