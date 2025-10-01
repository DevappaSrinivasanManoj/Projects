Echo API with Custom Status Code
This API is a simple echo service that:

Accepts a JSON payload in a POST request.

Allows the client to specify a custom HTTP status code in the request payload (via the status_code field).

Returns the same JSON payload in the response, excluding the status_code field.

Sets the HTTP response status code to the value provided in the request (defaults to 200 OK if not specified).

Key Features
Flexible Status Codes:

Clients can specify any valid HTTP status code (e.g., 200, 201, 400, 404, 500).

Clean Response:

The status_code field is removed from the response body to avoid redundancy.

Use Cases:

Testing and debugging HTTP clients.

Simulating different server responses (e.g., success, errors).

Learning and experimenting with APIs.
