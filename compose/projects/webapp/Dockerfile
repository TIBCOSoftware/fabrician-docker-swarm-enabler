FROM python:2.7
WORKDIR /
COPY app.py /
COPY requirements.txt /
RUN pip install --upgrade pip
RUN pip install -r requirements.txt
CMD python app.py
