curl -X POST http://host.docker.internal:11434/v1/chat/completions \
-H "Content-Type: application/json" \
-d '{
  "model": "llama3.1",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "system", "content": "The current system time is 2024-09-01T12:34:56Z UTC."},
    {"role": "user", "content": "Can you remind me to call my partner tomorrow?"}
  ]
}'

curl -X GET http://host.docker.internal:11434