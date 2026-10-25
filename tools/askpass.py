import json
import os
import socket
import sys


def main():
    with socket.create_connection(('127.0.0.1', int(os.environ['RD05_AUTH_PORT'])), timeout=120) as connection:
        request = {'token': os.environ['RD05_AUTH_TOKEN'], 'prompt': ' '.join(sys.argv[1:])}
        connection.sendall(json.dumps(request).encode() + b'\n')
        with connection.makefile('rb') as response:
            answer = json.loads(response.readline(16384))
    print(answer)


if __name__ == '__main__':
    main()
