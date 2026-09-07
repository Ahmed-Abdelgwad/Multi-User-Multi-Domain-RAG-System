# Build stage
FROM python:3.11-slim

WORKDIR /app

# tesseract-ocr: OCR fallback for scanned PDFs (spec 2.1).
# poppler-utils: gives pdf2image the `pdftoppm`/`pdftocairo` binaries it
# shells out to when rendering PDF pages for that OCR fallback.
# ghostscript: Camelot's PDF table extraction (both lattice and stream
# flavors) shells out to it for page rendering/text positioning.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    ghostscript \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies. pip is upgraded first -- the base image's pip
# (24.0) failed to resolve requirements.txt once sentence-transformers
# (phase 3) was added (ResolutionImpossible on fastapi/pydantic, despite
# there being a valid resolution); a current pip resolves it cleanly.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# CPU-only torch, installed *before* sentence-transformers and from
# PyTorch's own CPU wheel index -- left to its default resolution, pip
# pulls the CUDA/GPU build of torch (2.14.0 pulled in nvidia-cudnn-cu13,
# nvidia-cublas, a full cuda-toolkit, triton, etc: several GB of NVIDIA
# libraries that sat completely unused on this host, which has no GPU,
# and turned the build into an hours-long download on this connection).
# Installing the small CPU wheel first means sentence-transformers' own
# `torch>=2.2` requirement is already satisfied and pip never reaches
# for the GPU build at all.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# sentence-transformers (phase 3's embedding model) is installed in its
# own step, deliberately kept out of requirements.txt: solving it jointly
# with langchain-community's own dependency tree pushed pip's resolver
# past its search-depth limit ("resolution-too-deep", pip spending 1000+
# seconds backtracking through transitive versions before giving up).
# Installing it separately, after everything else (including CPU torch
# above) is already satisfied, is a much smaller resolution problem.
# Version pinned for reproducible builds -- it also fixes the exact
# transformers/tokenizers/huggingface_hub versions it needs, which is
# the compatible set proven at the time this was pinned.
RUN pip install --no-cache-dir sentence-transformers==6.0.1

# gliner2 (phase 7's entity/relation extraction model, spec 2.5) --
# installed in its own step for the same reason as sentence-transformers
# above: it shares torch/transformers with it, so resolving it after both
# are already satisfied avoids the same resolution-too-deep risk. The
# `[local]` extra pulls in what's needed to run the model locally
# (as opposed to Fastino's hosted API).
#
# protobuf: not a gliner2/transformers install-time dependency, but a
# real *runtime* one -- fastino/gliner2.5-multi-v1's mDeBERTa-v3-base
# backbone uses a SentencePiece-based tokenizer, and transformers needs
# protobuf to load it. Missing this doesn't fail until the model is
# actually loaded (first real extraction), which is exactly how this was
# caught live: "requires the protobuf library but it was not found".
RUN pip install --no-cache-dir "gliner2[local]" protobuf

# Copy the project files
COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .

# Expose the port FastAPI runs on
EXPOSE 8000

# Run the FastAPI application
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]