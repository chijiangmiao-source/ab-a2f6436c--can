# End-to-end acceptance image for the CAN filter audit stack.
# Build context is the repository root so backend sources/tests are included.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir pytest==8.3.4

WORKDIR /acceptance

# Backend sources + unit tests (exercised against the same solver package
# the API image ships).
COPY backend/app ./app
COPY backend/test_solver.py ./test_solver.py
COPY acceptance/verify.py ./verify.py
COPY acceptance/run.sh ./run.sh
RUN chmod +x ./run.sh

CMD ["./run.sh"]
