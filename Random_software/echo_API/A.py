from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/echo', methods=['POST'])
def echo():
    # Get the JSON payload from the request
    data = request.json
    # Extract the status_code from the payload (default to 200 if not provided)
    status_code = data.pop('status_code', 200)
    # Return the same payload as the response with the specified status code
    return jsonify(data), status_code

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000) #The host='0.0.0.0' and port=5000 is to make the API accessible to other PCs in the same network.
