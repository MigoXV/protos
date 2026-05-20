python -m grpc_tools.protoc \
    -I src \
    --python_out=src \
    --grpc_python_out=src \
    --mypy_out=src \
    --mypy_grpc_out=src \
src/{包名}/protos/{功能}/{功能}.proto
