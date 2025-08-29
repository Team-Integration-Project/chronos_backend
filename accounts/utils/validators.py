import re

def validate_cpf(cpf):
    if not re.match(r'^\d{11}$', cpf):
        return False, 'CPF deve conter 11 dígitos numéricos.'
    return True, ""

def validate_phone_number(phone_number):
    if not re.match(r'^\d{10,11}$', phone_number):
        return False, 'Telefone deve conter 10 ou 11 dígitos numéricos.'
    return True, ""
