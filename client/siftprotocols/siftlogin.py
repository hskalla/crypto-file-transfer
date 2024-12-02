#python3

import time
from Crypto.Hash import SHA256
from Crypto.Protocol.KDF import PBKDF2
from siftprotocols.siftmtp import SiFT_MTP, SiFT_MTP_Error
import Crypto.Random
from Crypto.Protocol.KDF import HKDF


class SiFT_LOGIN_Error(Exception):

    def __init__(self, err_msg):
        self.err_msg = err_msg

class SiFT_LOGIN:
    def __init__(self, mtp):

        self.DEBUG = True
        # --------- CONSTANTS ------------
        self.delimiter = '\n'
        self.coding = 'utf-8'
        self.random_size = 16
        self.statefile = "state.txt"
        # --------- STATE ------------
        self.mtp = mtp
        self.server_users = None 


    # sets user passwords dictionary (to be used by the server)
    def set_server_users(self, users):
        self.server_users = users


    # builds a login request from a dictionary
    def build_login_req(self, login_req_struct):

        login_req_str = str(login_req_struct['timestamp'])
        login_req_str += self.delimiter + login_req_struct['username'] 
        login_req_str += self.delimiter + login_req_struct['password'] 
        login_req_str += self.delimiter + login_req_struct['random'].hex()
        return login_req_str.encode(self.coding)


    # parses a login request into a dictionary
    def parse_login_req(self, login_req):

        login_req_fields = login_req.decode(self.coding).split(self.delimiter)
        login_req_struct = {}
        login_req_struct['timestamp'] = int(login_req_fields[0])
        login_req_struct['username'] = login_req_fields[1]
        login_req_struct['password'] = login_req_fields[2]
        login_req_struct['random'] = bytes.fromhex(login_req_fields[3])
        return login_req_struct


    # builds a login response from a dictionary
    def build_login_res(self, login_res_struct):

        login_res_str = login_res_struct['request_hash'].hex() 
        login_res_str += self.delimiter + login_res_struct['random'].hex()
        return login_res_str.encode(self.coding)


    # parses a login response into a dictionary
    def parse_login_res(self, login_res):
        login_res_fields = login_res.decode(self.coding).split(self.delimiter)
        login_res_struct = {}
        login_res_struct['request_hash'] = bytes.fromhex(login_res_fields[0])
        login_res_struct['random'] = bytes.fromhex(login_res_fields[1])
        return login_res_struct


    # check correctness of a provided password
    def check_password(self, pwd, usr_struct):

        pwdhash = PBKDF2(pwd, usr_struct['salt'], len(usr_struct['pwdhash']), count=usr_struct['icount'], hmac_hash_module=SHA256)
        if pwdhash == usr_struct['pwdhash']: return True
        return False


    # handles login process (to be used by the server)
    def handle_login_server(self):

        if not self.server_users:
            raise SiFT_LOGIN_Error('User database is required for handling login at server')

        # trying to receive a login request
        try:
            msg_type, msg_payload = self.mtp.receive_msg()
        except SiFT_MTP_Error as e:
            raise SiFT_LOGIN_Error('Unable to receive login request --> ' + e.err_msg)

        # DEBUG 
        if self.DEBUG:
            print('Incoming payload (' + str(len(msg_payload)) + '):')
            print(msg_payload[:max(512, len(msg_payload))].decode('utf-8'))
            print('------------------------------------------')
        # DEBUG 

        if msg_type != self.mtp.type_login_req:
            raise SiFT_LOGIN_Error('Login request expected, but received something else')

        # processing login request
        hash_fn = SHA256.new()
        hash_fn.update(msg_payload)
        request_hash = hash_fn.digest()

        login_req_struct = self.parse_login_req(msg_payload)

        # checking username and password
        if login_req_struct['username'] in self.server_users:
            if not self.check_password(login_req_struct['password'], self.server_users[login_req_struct['username']]):
                raise SiFT_LOGIN_Error('Password verification failed')
        else:
            raise SiFT_LOGIN_Error('Unkown user attempted to log in')

        # check timestamp validity
        current_time = time.time_ns()
        timestamp = login_req_struct['timestamp']
        if(abs(current_time - timestamp) > 1000000000):
            raise SiFT_LOGIN_Error('Timestamp outside of accepted range')

        # building login response
        login_res_struct = {}
        login_res_struct['request_hash'] = request_hash
        login_res_struct['random'] = Crypto.Random.get_random_bytes(self.random_size)
        msg_payload = self.build_login_res(login_res_struct)

        # DEBUG 
        if self.DEBUG:
            print('Outgoing payload (' + str(len(msg_payload)) + '):')
            print(msg_payload[:max(512, len(msg_payload))].decode('utf-8'))
            print('------------------------------------------')
        # DEBUG 

        # sending login response
        try:
            self.mtp.send_msg(self.mtp.type_login_res, msg_payload)
        except SiFT_MTP_Error as e:
            raise SiFT_LOGIN_Error('Unable to send login response --> ' + e.err_msg)

        # DEBUG 
        if self.DEBUG:
            print('User ' + login_req_struct['username'] + ' logged in')
        # DEBUG 

        # compute and write new key
        unsalted_key = login_req_struct['random'] + login_res_struct['random']
        key = HKDF(unsalted_key, 32, request_hash, SHA256)

        # read state file: key, sndsqn, rcvsqn
        ifile = open(self.statefile, 'rt')
        line = ifile.readline()
        line = ifile.readline()
        sndsqn = line[len("sndsqn: "):]
        sndsqn = int(sndsqn, base=10)
        line = ifile.readline()
        rcvsqn = line[len("rcvsqn: ")]
        rcvsqn = int(rcvsqn, base=10)
        ifile.close()

        # store seq number, key, by writing to file
        state =  "key: " + key.hex() + '\n'
        state += "sndsqn: " + str(sndsqn) + '\n'
        state += "rcvsqn: " + str(rcvsqn)
        with open(self.statefile, 'wt') as sf:
            sf.write(state)

        return login_req_struct['username']


    # handles login process (to be used by the client)
    def handle_login_client(self, username, password):

        # building a login request
        login_req_struct = {}
        login_req_struct['timestamp'] = time.time_ns()
        login_req_struct['username'] = username
        login_req_struct['password'] = password
        login_req_struct['random'] = Crypto.Random.get_random_bytes(self.random_size)
        msg_payload = self.build_login_req(login_req_struct)

        # DEBUG 
        if self.DEBUG:
            print('Outgoing payload (' + str(len(msg_payload)) + '):')
            print(msg_payload[:max(512, len(msg_payload))].decode('utf-8'))
            print('------------------------------------------')
        # DEBUG 

        # trying to send login request
        try:
            self.mtp.send_msg(self.mtp.type_login_req, msg_payload)
        except SiFT_MTP_Error as e:
            raise SiFT_LOGIN_Error('Unable to send login request --> ' + e.err_msg)

        # computing hash of sent request payload
        hash_fn = SHA256.new()
        hash_fn.update(msg_payload)
        request_hash = hash_fn.digest()

        # trying to receive a login response
        try:
            msg_type, msg_payload = self.mtp.receive_msg()
        except SiFT_MTP_Error as e:
            raise SiFT_LOGIN_Error('Unable to receive login response --> ' + e.err_msg)

        # DEBUG 
        if self.DEBUG:
            print('Incoming payload (' + str(len(msg_payload)) + '):')
            print(msg_payload[:max(512, len(msg_payload))].decode('utf-8'))
            print('------------------------------------------')
        # DEBUG 

        if msg_type != self.mtp.type_login_res:
            raise SiFT_LOGIN_Error('Login response expected, but received something else')

        # processing login response
        login_res_struct = self.parse_login_res(msg_payload)

        # checking request_hash received in the login response
        if login_res_struct['request_hash'] != request_hash:
            raise SiFT_LOGIN_Error('Verification of login response failed')
        
        # compute and write new key
        unsalted_key = login_req_struct['random'] + login_res_struct['random']
        key = HKDF(unsalted_key, 32, request_hash, SHA256)

        # read state file: key, sndsqn, rcvsqn
        ifile = open(self.statefile, 'rt')
        line = ifile.readline()
        line = ifile.readline()
        sndsqn = line[len("sndsqn: "):]
        sndsqn = int(sndsqn, base=10)
        line = ifile.readline()
        rcvsqn = line[len("rcvsqn: ")]
        rcvsqn = int(rcvsqn, base=10)
        ifile.close()

        # store seq number, key, by writing to file
        state =  "key: " + key.hex() + '\n'
        state += "sndsqn: " + str(sndsqn) + '\n'
        state += "rcvsqn: " + str(rcvsqn)
        with open(self.statefile, 'wt') as sf:
            sf.write(state)

