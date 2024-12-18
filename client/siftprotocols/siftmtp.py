#python3

import sys, getopt
import socket
import Crypto.Random
from Crypto.Cipher import AES
from Crypto.Cipher import PKCS1_OAEP
from Crypto.PublicKey import RSA


class SiFT_MTP_Error(Exception):

    def __init__(self, err_msg):
        self.err_msg = err_msg

class SiFT_MTP:
	def __init__(self, peer_socket):

		self.DEBUG = True
		# --------- CONSTANTS ------------
		self.version_major = 1
		self.version_minor = 0
		self.msg_hdr_ver = b'\x01\x00'
		self.msg_hdr_rsv = b'\x00\x00'

		# sizes of the message header components (in bytes)
		self.size_msg_hdr = 16
		self.size_msg_hdr_ver = 2
		self.size_msg_hdr_typ = 2
		self.size_msg_hdr_len = 2
		self.size_msg_hdr_sqn = 2
		self.size_msg_hdr_rnd = 6
		self.size_msg_hdr_rsv = 2

		# size of the encrypted key and computed mac value (in bytes)
		self.size_temp_key = 32
		self.size_enc_temp_key = 256
		self.size_msg_mac = 12

		self.type_login_req =    b'\x00\x00'
		self.type_login_res =    b'\x00\x10'
		self.type_command_req =  b'\x01\x00'
		self.type_command_res =  b'\x01\x10'
		self.type_upload_req_0 = b'\x02\x00'
		self.type_upload_req_1 = b'\x02\x01'
		self.type_upload_res =   b'\x02\x10'
		self.type_dnload_req =   b'\x03\x00'
		self.type_dnload_res_0 = b'\x03\x10'
		self.type_dnload_res_1 = b'\x03\x11'
		self.msg_types = (self.type_login_req, self.type_login_res, 
						  self.type_command_req, self.type_command_res,
						  self.type_upload_req_0, self.type_upload_req_1, self.type_upload_res,
						  self.type_dnload_req, self.type_dnload_res_0, self.type_dnload_res_1)
		# --------- STATE ------------
		self.peer_socket = peer_socket
		self.file_sqn = "./data/sqn.txt"
		self.file_sym_key = "./data/symkey.pem"
		self.file_public_key = "./data/pubkey.pem"
		self.file_private_key = "./data/prvkey.pem"


	# parses a message header and returns a dictionary containing the header fields
	def parse_msg_header(self, msg_hdr):

		parsed_msg_hdr, i = {}, 0
		parsed_msg_hdr['ver'], i = msg_hdr[i:i+self.size_msg_hdr_ver], i+self.size_msg_hdr_ver 
		parsed_msg_hdr['typ'], i = msg_hdr[i:i+self.size_msg_hdr_typ], i+self.size_msg_hdr_typ
		parsed_msg_hdr['len'], i = msg_hdr[i:i+self.size_msg_hdr_len], i+self.size_msg_hdr_len
		parsed_msg_hdr['sqn'], i = msg_hdr[i:i+self.size_msg_hdr_sqn], i+self.size_msg_hdr_sqn
		parsed_msg_hdr['rnd'], i = msg_hdr[i:i+self.size_msg_hdr_rnd], i+self.size_msg_hdr_rnd
		parsed_msg_hdr['rsv'] = msg_hdr[i:i+self.size_msg_hdr_rsv]
		return parsed_msg_hdr


	# receives n bytes from the peer socket
	def receive_bytes(self, n):

		bytes_received = b''
		bytes_count = 0
		while bytes_count < n:
			try:
				chunk = self.peer_socket.recv(n-bytes_count)
			except:
				raise SiFT_MTP_Error('Unable to receive via peer socket')
			if not chunk: 
				raise SiFT_MTP_Error('Connection with peer is broken')
			bytes_received += chunk
			bytes_count += len(chunk)
		return bytes_received


	# receives and parses message, returns msg_type and msg_payload
	def receive_msg(self):

		# read sequence number
		ifile = open(self.file_sqn, 'rt')
		line = ifile.readline()
		sndsqn = line[len("sndsqn: "):]
		sndsqn = int(sndsqn, base=10)
		line = ifile.readline()
		rcvsqn = line[len("rcvsqn: ")]
		rcvsqn = int(rcvsqn, base=10)
		ifile.close()

		# read file for symmetric key
		with open(self.file_sym_key,'rb') as f:
			key = f.read()

		# read header bytes
		try:
			msg_hdr = self.receive_bytes(self.size_msg_hdr)
		except SiFT_MTP_Error as e:
			raise SiFT_MTP_Error('Unable to receive message header --> ' + e.err_msg)

		if len(msg_hdr) != self.size_msg_hdr: 
			raise SiFT_MTP_Error('Incomplete message header received')
		
		# parse header and check for errors
		parsed_msg_hdr = self.parse_msg_header(msg_hdr)

		if parsed_msg_hdr['ver'] != self.msg_hdr_ver:
			raise SiFT_MTP_Error('Unsupported version found in message header')

		if parsed_msg_hdr['typ'] not in self.msg_types:
			raise SiFT_MTP_Error('Unknown message type found in message header')

		if parsed_msg_hdr['rsv'] != self.msg_hdr_rsv:
			raise SiFT_MTP_Error('Invalid rsv field found in message header')

		msg_len = int.from_bytes(parsed_msg_hdr['len'], byteorder='big')

		# special case for login request
		if parsed_msg_hdr['typ'] == self.type_login_req:
			# reset seq numbers
			sndsqn = 0
			rcvsqn = 0

			# read the server's private key from the file
			with open(self.file_private_key,'rb') as f:
				prvkeystr = f.read()
			try:
				private_key = RSA.import_key(prvkeystr)
			except ValueError:
				print("Error: Cannot import private key from file.")
				sys.exit(1)

			# enc temp key size is set to the normal key exchange size
			size_enc_temp_key_actual = self.size_enc_temp_key
		else:
			size_enc_temp_key_actual = 0

		# read msg body bytes
		try:
			msg_body = self.receive_bytes(msg_len - self.size_msg_hdr - self.size_msg_mac - size_enc_temp_key_actual)
		except SiFT_MTP_Error as e:
			raise SiFT_MTP_Error('Unable to receive message body --> ' + e.err_msg)
		
		# read mac bytes
		try:
			msg_mac = self.receive_bytes(self.size_msg_mac)
		except SiFT_MTP_Error as e:
			raise SiFT_MTP_Error('Unable to receive message mac --> ' + e.err_msg)
		
		# read login key (for key exchange)
		try:
			enc_temp_key = self.receive_bytes(size_enc_temp_key_actual)
		except SiFt_MTP_Error as e:
			raise SiFt_MTP_Error('Unable to recieve key in logic req --> ' + e.err_msg)

		# special case for login request
		if parsed_msg_hdr['typ'] == self.type_login_req:
			rsa = PKCS1_OAEP.new(private_key)
			key = rsa.decrypt(enc_temp_key)

			# store the temp key for later use
			with open(self.file_sym_key,'wb') as f:
				f.write(key)

		# verify sequence number
		if int.from_bytes(parsed_msg_hdr['sqn'], byteorder='big') <= rcvsqn:
			raise SiFT_MTP_Error('Invalid sequence number')
		else:
			# update sequence number
			rcvsqn = int.from_bytes(parsed_msg_hdr['sqn'], byteorder='big')
		
		# write seq to file
		sqn_state = "sndsqn: " + str(sndsqn) + '\n'
		sqn_state += "rcvsqn: " + str(rcvsqn)
		with open(self.file_sqn, 'wt') as sf:
			sf.write(sqn_state)

		# decrypt and verify message
		print("Decryption and authentication tag verification is attempted...")
		nonce = parsed_msg_hdr['sqn'] + parsed_msg_hdr['rnd']
		GCM = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=self.size_msg_mac)
		GCM.update(msg_hdr)
		try:
		    decrypted_payload = GCM.decrypt_and_verify(msg_body, msg_mac)
		except Exception as e:
			print("Error: Operation failed!")
			print("Processing completed.")
			sys.exit(1)
		print("Operation was successful: message is intact, content is decrypted.")

		# DEBUG 
		if self.DEBUG:
			print('MTP message received (' + str(msg_len) + '):')
			print('HDR (' + str(len(msg_hdr)) + '): ' + msg_hdr.hex())
			print('BDY (' + str(len(msg_body)) + '): ')
			print(msg_body.hex())
			print('DEC (' + str(len(decrypted_payload)) + '): ')
			print(decrypted_payload.hex())
			print('MAC (' + str(len(msg_mac)) + '): ')
			print(msg_mac.hex())
			if size_enc_temp_key_actual > 0:
				print('KEY (' + str(size_enc_temp_key_actual) + '): ')
				print(enc_temp_key.hex())
			print('------------------------------------------')
		# DEBUG 

		# verify for correct length of body
		if len(msg_body) != msg_len - self.size_msg_hdr - self.size_msg_mac - size_enc_temp_key_actual: 
			raise SiFT_MTP_Error('Incomplete message body reveived')
				
		return parsed_msg_hdr['typ'], decrypted_payload


	# sends all bytes provided via the peer socket
	def send_bytes(self, bytes_to_send):
		try:
			self.peer_socket.sendall(bytes_to_send)
		except:
			raise SiFT_MTP_Error('Unable to send via peer socket')


	# builds and sends message of a given type using the provided payload
	def send_msg(self, msg_type, msg_payload):
		
		# read sequence number
		ifile = open(self.file_sqn, 'rt')
		line = ifile.readline()
		sndsqn = line[len("sndsqn: "):]
		sndsqn = int(sndsqn, base=10)
		line = ifile.readline()
		rcvsqn = line[len("rcvsqn: ")]
		rcvsqn = int(rcvsqn, base=10)
		ifile.close()

		# read file for symmetric key
		with open(self.file_sym_key,'rb') as f:
			key = f.read()

		# special case for login request
		if msg_type == self.type_login_req:
			# reset sequence number
			sndsqn = 0
			rcvsqn = 0
			
			# read the server's public key from the file
			with open(self.file_public_key, 'rb') as f:
				pubkeystr = f.read()
			try:
				public_key = RSA.import_key(pubkeystr)
			except ValueError:
				print("Error: Cannot import public key from file.")
				sys.exit(1)

			# if this is a login request, enc temp key size is 256, otherwise, its 0
			size_enc_temp_key_actual = self.size_enc_temp_key
			temp_key = Crypto.Random.get_random_bytes(self.size_temp_key)

			# if this is a login request, we use the temp key for encryption
			key = temp_key

			# store the temp key for use decrypting the login response
			with open(self.file_sym_key,'wb') as f:
				f.write(key)

			# encrypt the msg key
			rsa = PKCS1_OAEP.new(public_key)
			enc_temp_key = rsa.encrypt(temp_key)
		else:
			size_enc_temp_key_actual = 0
			enc_temp_key = b''
	
		# update sequence number
		sndsqn = sndsqn + 1

		# build message header
		msg_size = self.size_msg_hdr + len(msg_payload) + self.size_msg_mac + size_enc_temp_key_actual
		msg_hdr_len = msg_size.to_bytes(self.size_msg_hdr_len, byteorder='big')
		msg_hdr_sqn = sndsqn.to_bytes(2, byteorder='big')
		msg_hdr_rnd = Crypto.Random.get_random_bytes(6)
		msg_hdr = self.msg_hdr_ver + msg_type + msg_hdr_len + msg_hdr_sqn + msg_hdr_rnd + self.msg_hdr_rsv

		# encrypt payload and get MAC with AES in GCM mode
		nonce = msg_hdr_sqn + msg_hdr_rnd
		GSM = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=self.size_msg_mac)
		GSM.update(msg_hdr)
		encrypted_payload, msg_mac = GSM.encrypt_and_digest(msg_payload)

		# DEBUG 
		if self.DEBUG:
			print('MTP message to send (' + str(msg_size) + '):')
			print('HDR (' + str(len(msg_hdr)) + '): ' + msg_hdr.hex())
			print('BDY (' + str(len(msg_payload)) + '): ')
			print(msg_payload.hex())
			print('ENC (' + str(len(encrypted_payload)) + '): ')
			print(encrypted_payload.hex())
			print('MAC (' + str(len(msg_mac)) + '): ')
			print(msg_mac.hex())
			if size_enc_temp_key_actual > 0:
				print('KEY (' + str(size_enc_temp_key_actual) + '): ')
				print(enc_temp_key.hex())
			print('------------------------------------------')
		# DEBUG 

		# try to send
		try:
			self.send_bytes(msg_hdr + encrypted_payload + msg_mac + enc_temp_key)

			# write seq number to file
			sqn_state = "sndsqn: " + str(sndsqn) + '\n'
			sqn_state += "rcvsqn: " + str(rcvsqn)
			with open(self.file_sqn, 'wt') as sf:
				sf.write(sqn_state)
			
		except SiFT_MTP_Error as e:
			raise SiFT_MTP_Error('Unable to send message to peer --> ' + e.err_msg)