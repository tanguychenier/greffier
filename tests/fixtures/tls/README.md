# A test-only TLS key pair

`certificat.pem` and `cle.pem` are the self-signed certificate and private key
of a mail server that exists only inside `tests/test_email_smtp.py`. The key
protects nothing: it is committed on purpose, so that the tests run the same on
every machine, and it must never be used for anything else.

Made once, with OpenSSL 3.0.13:

```sh
openssl req -x509 -newkey rsa:2048 -nodes -days 36500 \
    -keyout cle.pem -out certificat.pem \
    -subj "/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
```

The subject alternative name carries `IP:127.0.0.1`, which is what the tests
connect to: Python's default context checks the host name, and the accepted case
must pass that check too, not only the signature. 36 500 days, so that nobody
has to regenerate it in this lifetime.
