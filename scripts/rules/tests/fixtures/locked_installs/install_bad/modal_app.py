import modal

image = modal.Image.debian_slim().pip_install("numpy")
