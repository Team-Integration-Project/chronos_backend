# Projeto de Autenticação Facial com Django

Este é um projeto de autenticação que combina login e registro usando email, senha e reconhecimento facial. Ele utiliza Django como framework, Django REST Framework (DRF) para a API, PostgreSQL com a extensão `pgvector` para armazenar embeddings faciais, e a biblioteca `face_recognition` para processar imagens faciais. Este README fornece instruções detalhadas para configurar e rodar o projeto localmente.

## Pré-requisitos

Antes de começar, certifique-se de ter os seguintes itens instalados:

- **Python 3.8 ou superior** (recomendado: 3.10 ou 3.11)
- **PostgreSQL 13 ou superior** (para armazenar os embeddings faciais)
- **Git** (para clonar o repositório)
- **pip** e **venv** (gerenciador de ambiente virtual do Python)

### Ferramentas Opcionais
- **Postman** ou outro cliente API (para testar os endpoints)
- **Editor de código** (ex.: VSCode, PyCharm)

## Instalação

Siga os passos abaixo para configurar o projeto em sua máquina local.

### 1. Clone o Repositório
```bash
git clone https://github.com/Team-Integration-Project/integration_project_backend.git
cd integration_project_backend
```

### 2. Crie um Ambiente Virtual
Crie e ative um ambiente virtual para isolar as dependências:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

### 3. Instale as Dependências
Instale as bibliotecas necessárias usando o arquivo `requirements.txt`. Se ele ainda não existir, crie um com os pacotes listados abaixo e execute:
```bash
pip install -r requirements.txt
```
Se precisar criar o `requirements.txt`, use:
```bash
pip freeze > requirements.txt
```
Os pacotes principais são:
- `django`
- `djangorestframework`
- `django-rest-framework-simplejwt`
- `face_recognition`
- `opencv-python`
- `numpy`
- `psycopg2-binary`
- `pgvector`

**Nota**: A instalação do `face_recognition` requer `cmake` e `dlib`. No Ubuntu, instale:
```bash
sudo apt-get install build-essential cmake libopenblas-dev liblapack-dev libjpeg-dev
```
No Windows, siga as instruções no [site oficial do dlib](http://dlib.net/compile.html).

### 4. Configure o Banco de Dados
- **Instale e Inicie o PostgreSQL**:
  - No Ubuntu: `sudo apt-get install postgresql postgresql-contrib`
  - No Windows/Mac: Baixe e instale via [site oficial](https://www.postgresql.org/download/).
  - Inicie o serviço: `sudo service postgresql start` (Ubuntu) ou use o pgAdmin.

- **Crie um Banco de Dados**:
  Acesse o PostgreSQL como usuário `postgres`:
  ```bash
  psql -U postgres
  ```
  Crie o banco:
  ```sql
  CREATE DATABASE ponto_eletronico;
  \c ponto_eletronico
  CREATE EXTENSION vector;
  ```

- **Configure as Credenciais**:
  Edite `management/settings.py` e ajuste o bloco `DATABASES`:
  ```python
  DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': 'ponto_eletronico',
            'USER': 'postgres',
            'PASSWORD': 'SUA_SENHA',
            'HOST': 'localhost',
            'PORT': '5432',
        }
  }
  ```
  Substitua `'sua_senha'` pela senha do usuário `postgres` no seu PostgreSQL.

### 5. Configure o Projeto
- **Aplique as Migrações**:
  Crie e aplique as migrações para o modelo `CustomUser`:
  ```bash
  python manage.py makemigrations
  python manage.py migrate
  ```

- **Crie um Superusuário** (opcional, para acessar o admin):
  ```bash
  python manage.py createsuperuser
  ```

### 6. Rode o Servidor
Inicie o servidor Django:
```bash
python manage.py runserver
```
Acesse `http://127.0.0.1:8000` no navegador. Você verá uma página de erro padrão do Django, o que é esperado, pois o projeto é uma API.

## Uso

### Testando os Endpoints
Use o Postman ou `curl` para testar os endpoints de registro e login.

#### Registro (`/api/register/`)
- **Método**: `POST`
- **URL**: `http://127.0.0.1:8000/api/register/`
- **Body**: `form-data`
  ```
  Key          | Value
  -------------|--------------------
  username     | seu_usuario
  email        | seu_email@exemplo.com
  password     | sua_senha
  face_image   | [Selecione uma imagem facial .jpg ou .png]
  ```
- **Resposta Esperada** (status `201 Created`):
  ```json
  {
      "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
      "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
      "user": {
          "username": "seu_usuario",
          "email": "seu_email@exemplo.com"
      }
  }
  ```

#### Login (`/api/login/`)
- **Método**: `POST`
- **URL**: `http://127.0.0.1:8000/api/login/`
- **Body**: `form-data`
  ```
  Key          | Value
  -------------|--------------------
  email        | seu_email@exemplo.com
  password     | sua_senha
  face_image   | [Selecione uma imagem facial .jpg ou .png]
  ```
- **Resposta Esperada** (status `200 OK`):
  ```json
  {
      "refresh": "eyJ0eXAiOiJKV1QiLCJalbGciOiJIUzI1NiJ9...",
      "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
      "user": {
          "username": "seu_usuario",
          "email": "seu_email@exemplo.com"
      }
  }
  ```

## Estrutura do Projeto
```
integration_project_backend/
├── management/    # Configurações do Django
├── accounts/              # App principal com modelos, serializers e views
├── venv/                  # Ambiente virtual
├── requirements.txt       # Dependências
├── manage.py             # Script de gerenciamento do Django
└── README.md             # Este arquivo
```

## Contribuindo
- Faça fork do repositório.
- Crie uma branch para suas alterações: `git checkout -b feature/nova-funcionalidade`.
- Envie suas alterações: `git commit -m "Descrição da alteração"`.
- Envie para o repositório remoto: `git push origin feature/nova-funcionalidade`.
- Abra um Pull Request.

## Suporte
Para dúvidas, abra uma issue no repositório.