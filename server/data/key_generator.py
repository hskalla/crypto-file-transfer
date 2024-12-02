from Crypto.PublicKey import RSA

key_pair = RSA.generate(2048)

public_key = key_pair.public_key()
private_key = key_pair

with open("pubkey.pem",'wb') as f:
    f.write(public_key.export_key(format='PEM'))

with open("prvkey.pem",'wb') as f:
    f.write(private_key.export_key(format='PEM'))
