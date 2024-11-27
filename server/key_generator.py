from Crypto.PublicKey import RSA

key = RSA.generate(2048)
private_key = key.export_key()

public_key = key.publickey().export_key()


with open("rsa_keys.txt", "wt") as f:
    f.write("private key: "+private_key.hex() + '\npublic key: '+ public_key.hex())
