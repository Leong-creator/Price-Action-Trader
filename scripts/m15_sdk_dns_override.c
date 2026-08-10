#define _GNU_SOURCE

#include <arpa/inet.h>
#include <dlfcn.h>
#include <netdb.h>
#include <stdlib.h>
#include <string.h>

typedef int (*getaddrinfo_fn)(
    const char *, const char *, const struct addrinfo *, struct addrinfo **
);

static getaddrinfo_fn real_getaddrinfo(void) {
    static getaddrinfo_fn function = NULL;
    if (function == NULL) {
        function = (getaddrinfo_fn)dlsym(RTLD_NEXT, "getaddrinfo");
    }
    return function;
}

static const char *mapped_address(const char *node) {
    const char *mapping = getenv("M15_LONGBRIDGE_DNS_OVERRIDES");
    static _Thread_local char address[INET6_ADDRSTRLEN];
    const char *cursor;

    if (node == NULL || mapping == NULL || *mapping == '\0') {
        return NULL;
    }
    cursor = mapping;
    while (*cursor != '\0') {
        const char *equals = strchr(cursor, '=');
        const char *end = strchr(cursor, ';');
        size_t host_length;
        size_t address_length;
        if (end == NULL) {
            end = cursor + strlen(cursor);
        }
        if (equals == NULL || equals >= end) {
            cursor = *end == ';' ? end + 1 : end;
            continue;
        }
        host_length = (size_t)(equals - cursor);
        address_length = (size_t)(end - equals - 1);
        if (
            strlen(node) == host_length
            && strncmp(node, cursor, host_length) == 0
            && address_length > 0
            && address_length < sizeof(address)
        ) {
            memcpy(address, equals + 1, address_length);
            address[address_length] = '\0';
            return address;
        }
        cursor = *end == ';' ? end + 1 : end;
    }
    return NULL;
}

int getaddrinfo(
    const char *node,
    const char *service,
    const struct addrinfo *hints,
    struct addrinfo **result
) {
    getaddrinfo_fn function = real_getaddrinfo();
    const char *override = mapped_address(node);
    if (function == NULL) {
        return EAI_SYSTEM;
    }
    return function(override == NULL ? node : override, service, hints, result);
}
