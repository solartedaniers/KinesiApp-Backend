import logging

import dns.exception
import dns.resolver
from email_validator import validate_email
from email_validator.deliverability import validate_email_deliverability
from email_validator.exceptions import EmailUndeliverableError

logger = logging.getLogger(__name__)

# Tomo como definitivas estas respuestas DNS: el dominio no existe o no tiene dónde recibir correo
_DEFINITIVE_DNS_ANSWERS = (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer)


class EmailDomainChecker:
    """Compruebo por DNS (MX, o A/AAAA de respaldo) que el dominio de un correo pueda recibir mensajes.

    Solo rechazo ante una respuesta definitiva. Si el DNS no responde (timeout, sin servidores, red
    caída), dejo pasar el correo con un warning: un problema transitorio no debe impedir el registro.
    """

    def __init__(self, timeout_seconds: int) -> None:
        self._timeout_seconds = timeout_seconds

    def is_deliverable(self, email: str) -> bool:
        # El formato ya lo validó el schema (EmailStr); aquí solo saco el dominio normalizado
        domain = validate_email(email, check_deliverability=False)
        try:
            info = validate_email_deliverability(domain.ascii_domain, domain.domain, timeout=self._timeout_seconds)
        except EmailUndeliverableError as error:
            # Lo tomo como definitivo sin causa (MX nulo, SPF que prohíbe enviar) o con NXDOMAIN/NoAnswer.
            # Con otra causa, la librería envolvió una falla inesperada de la consulta
            if error.__cause__ is None or isinstance(error.__cause__, _DEFINITIVE_DNS_ANSWERS):
                return False
            logger.warning("Email domain check failed for %s, accepting format only: %s", domain.domain, error)
            return True
        except dns.exception.DNSException as error:
            # Capturo lo que la librería no maneja, p. ej. un sistema sin resolver configurado
            logger.warning("Email domain check unavailable for %s, accepting format only: %s", domain.domain, error)
            return True
        if "unknown-deliverability" in info:
            logger.warning(
                "Email domain check inconclusive for %s (%s), accepting format only",
                domain.domain,
                info["unknown-deliverability"],
            )
        return True
