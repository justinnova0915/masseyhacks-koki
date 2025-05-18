import socket

HOST = '0.0.0.0'
PORT = 9997

print(f"Minimal server attempting to listen on {HOST}:{PORT}...")
try:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, PORT))
        s.listen()
        print(f"Minimal server listening on {HOST}:{PORT}")
        print("Waiting for a connection...")
        try:
            conn, addr = s.accept() # This is blocking
            print(f"Minimal server ACCEPTED connection from {addr}")
            with conn:
                print(f"Connected by {addr}")
                # Keep connection open for a bit, then close
                data = conn.recv(1024) # Try to receive something
                if data:
                    print(f"Received from client: {data.decode(errors='ignore')}")
                else:
                    print("Client sent no data or closed connection early.")
        except Exception as e_accept:
            print(f"Error during accept or handling connection: {e_accept}")
        finally:
            print("Minimal server connection attempt finished.")
except Exception as e_bind:
    print(f"Error setting up minimal server: {e_bind}")

print("Minimal server script finished.")
