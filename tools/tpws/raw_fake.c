#define _GNU_SOURCE
#include "raw_fake.h"
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/tcp.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static char sni_names[64][254];
static size_t sni_count;
static char sni_path[PATH_MAX];

static bool valid_sni(const char *name)
{
    size_t length = strlen(name), label = 0;
    if (!length || length > 253) return false;
    for (size_t i = 0; i < length; i++) {
        unsigned char c = name[i];
        if (c == '.') {
            if (!label || name[i - 1] == '-') return false;
            label = 0;
        } else {
            if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                  (c >= '0' && c <= '9') || (c == '-' && label))) return false;
            if (++label > 63) return false;
        }
    }
    return label && name[length - 1] != '-';
}

bool raw_fake_sni_load(const char *path)
{
    if (!path || strlen(path) >= sizeof(sni_path)) { errno = EINVAL; return false; }
    FILE *file = fopen(path, "r");
    if (!file) return false;
    char names[64][254] = {{0}}, line[512];
    size_t count = 0;
    bool valid = true;
    while (fgets(line, sizeof(line), file)) {
        if (!strchr(line, '\n') && !feof(file)) { valid = false; break; }
        char *comment = strchr(line, '#');
        if (comment) *comment = 0;
        char *start = line + strspn(line, " \t\r\n");
        size_t length = strlen(start);
        while (length && strchr(" \t\r\n", start[length - 1])) start[--length] = 0;
        if (!length) continue;
        if (count == 64 || !valid_sni(start)) { valid = false; break; }
        memcpy(names[count++], start, length + 1);
    }
    if (ferror(file)) valid = false;
    fclose(file);
    if (!valid || !count) { errno = EINVAL; return false; }
    memcpy(sni_names, names, sizeof(names));
    sni_count = count;
    memmove(sni_path, path, strlen(path) + 1);
    return true;
}

bool raw_fake_sni_reload(void)
{
    return !sni_path[0] || raw_fake_sni_load(sni_path);
}

static unsigned int get16(const uint8_t *p)
{
    return ((unsigned int)p[0] << 8) | p[1];
}

static void put16(uint8_t *p, unsigned int value)
{
    p[0] = value >> 8;
    p[1] = value;
}

static void put32(uint8_t *p, uint32_t value)
{
    p[0] = value >> 24;
    p[1] = value >> 16;
    p[2] = value >> 8;
    p[3] = value;
}

bool raw_fake_payload(const uint8_t *payload, size_t size, uint8_t *output, size_t *output_size)
{
    if (!payload || !output || !output_size || size > *output_size) { errno = EINVAL; return false; }
    if (!sni_count) {
        memcpy(output, payload, size);
        *output_size = size;
        return true;
    }
    if (size < 44 || payload[0] != 22 || payload[5] != 1 || get16(payload + 3) + 5 != size ||
        (((size_t)payload[6] << 16) | ((size_t)payload[7] << 8) | payload[8]) + 9 != size) {
        errno = EINVAL;
        return false;
    }
    size_t position = 43;
    position += 1 + payload[position];
    if (position + 2 > size) { errno = EINVAL; return false; }
    position += 2 + get16(payload + position);
    if (position >= size) { errno = EINVAL; return false; }
    position += 1 + payload[position];
    if (position + 2 > size) { errno = EINVAL; return false; }
    size_t extensions = position;
    size_t end = position + 2 + get16(payload + position);
    if (end != size) { errno = EINVAL; return false; }
    position += 2;
    while (position + 4 <= end) {
        size_t length = get16(payload + position + 2);
        if (position + 4 + length > end) break;
        if (!get16(payload + position)) {
            if (length < 5 || get16(payload + position + 4) != length - 2 ||
                payload[position + 6] || get16(payload + position + 7) != length - 5) break;
            uint32_t random;
            int source = open("/dev/urandom", O_RDONLY | O_CLOEXEC);
            if (source < 0) return false;
            ssize_t received;
            do { received = read(source, &random, sizeof(random)); } while (received < 0 && errno == EINTR);
            int saved = errno;
            close(source);
            if (received != sizeof(random)) { errno = received < 0 ? saved : EIO; return false; }
            const char *name = sni_names[random % sni_count];
            size_t old_length = length - 5, new_length = strlen(name);
            size_t total = size - old_length + new_length;
            if (total > *output_size || total > 1200) { errno = EOVERFLOW; return false; }
            size_t host = position + 9;
            memcpy(output, payload, host);
            memcpy(output + host, name, new_length);
            memcpy(output + host + new_length, payload + host + old_length, size - host - old_length);
            put16(output + 3, total - 5);
            output[6] = (total - 9) >> 16;
            put16(output + 7, total - 9);
            put16(output + extensions, get16(payload + extensions) - old_length + new_length);
            put16(output + position + 2, new_length + 5);
            put16(output + position + 4, new_length + 3);
            put16(output + position + 7, new_length);
            *output_size = total;
            return true;
        }
        position += 4 + length;
    }
    errno = EINVAL;
    return false;
}

static unsigned int checksum(const uint8_t *p, size_t size)
{
    unsigned int sum = 0;
    while (size > 1) {
        sum += ((unsigned int)p[0] << 8) | p[1];
        p += 2;
        size -= 2;
    }
    if (size) sum += (unsigned int)p[0] << 8;
    while (sum >> 16) sum = (sum & 65535) + (sum >> 16);
    return (~sum) & 65535;
}

static bool socket_address(int fd, bool peer, struct sockaddr_storage *address)
{
    socklen_t size = sizeof(*address);
    if ((peer ? getpeername(fd, (void *)address, &size) : getsockname(fd, (void *)address, &size))) return false;
    if (address->ss_family == AF_INET6) {
        struct sockaddr_in6 *v6 = (void *)address;
        if (IN6_IS_ADDR_V4MAPPED(&v6->sin6_addr)) {
            struct sockaddr_in v4 = {.sin_family = AF_INET, .sin_port = v6->sin6_port};
            memcpy(&v4.sin_addr, v6->sin6_addr.s6_addr + 12, 4);
            memset(address, 0, sizeof(*address));
            memcpy(address, &v4, sizeof(v4));
        }
    }
    return address->ss_family == AF_INET || address->ss_family == AF_INET6;
}

static bool socket_sequences(int fd, uint32_t *sequence, uint32_t *acknowledgment)
{
    int enabled = 1, queue = TCP_SEND_QUEUE;
    socklen_t size = sizeof(*sequence);
    if (setsockopt(fd, IPPROTO_TCP, TCP_REPAIR, &enabled, sizeof(enabled))) return false;
    int result = setsockopt(fd, IPPROTO_TCP, TCP_REPAIR_QUEUE, &queue, sizeof(queue));
    if (!result) result = getsockopt(fd, IPPROTO_TCP, TCP_QUEUE_SEQ, sequence, &size);
    queue = TCP_RECV_QUEUE;
    if (!result) result = setsockopt(fd, IPPROTO_TCP, TCP_REPAIR_QUEUE, &queue, sizeof(queue));
    if (!result) result = getsockopt(fd, IPPROTO_TCP, TCP_QUEUE_SEQ, acknowledgment, &size);
    int saved = errno;
    enabled = 0;
    if (setsockopt(fd, IPPROTO_TCP, TCP_REPAIR, &enabled, sizeof(enabled))) return false;
    errno = saved;
    return result == 0;
}

bool raw_fake_send(int fd, const uint8_t *payload, size_t size, uint8_t ttl, bool md5)
{
    if (!size || size > 1200 || !ttl) { errno = EINVAL; return false; }
    uint8_t randomized[1200];
    if (sni_count) {
        size_t randomized_size = sizeof(randomized);
        if (!raw_fake_payload(payload, size, randomized, &randomized_size)) return false;
        payload = randomized;
        size = randomized_size;
    }
    struct sockaddr_storage local, remote;
    if (!socket_address(fd, false, &local) || !socket_address(fd, true, &remote) || local.ss_family != remote.ss_family) return false;
    uint32_t sequence, acknowledgment;
    if (!socket_sequences(fd, &sequence, &acknowledgment)) return false;
    bool v6 = remote.ss_family == AF_INET6;
    size_t ip_size = v6 ? 40 : 20, tcp_size = md5 ? 40 : 20;
    uint8_t packet[1280] = {0}, pseudo[1280] = {0};
    uint8_t *tcp = packet + ip_size;
    size_t total = ip_size + tcp_size + size, pseudo_size = v6 ? 40 : 12;
    socklen_t remote_size;
    if (v6) {
        struct sockaddr_in6 *source = (void *)&local, *destination = (void *)&remote;
        packet[0] = 0x60;
        put16(packet + 4, tcp_size + size);
        packet[6] = IPPROTO_TCP;
        packet[7] = ttl;
        memcpy(packet + 8, &source->sin6_addr, 16);
        memcpy(packet + 24, &destination->sin6_addr, 16);
        memcpy(tcp, &source->sin6_port, 2);
        memcpy(tcp + 2, &destination->sin6_port, 2);
        memcpy(pseudo, packet + 8, 32);
        put32(pseudo + 32, tcp_size + size);
        pseudo[39] = IPPROTO_TCP;
        remote_size = sizeof(*destination);
    } else {
        struct sockaddr_in *source = (void *)&local, *destination = (void *)&remote;
        packet[0] = 0x45;
        put16(packet + 2, total);
        put16(packet + 4, sequence);
        packet[8] = ttl;
        packet[9] = IPPROTO_TCP;
        memcpy(packet + 12, &source->sin_addr, 4);
        memcpy(packet + 16, &destination->sin_addr, 4);
        memcpy(tcp, &source->sin_port, 2);
        memcpy(tcp + 2, &destination->sin_port, 2);
        memcpy(pseudo, packet + 12, 8);
        pseudo[9] = IPPROTO_TCP;
        put16(pseudo + 10, tcp_size + size);
        put16(packet + 10, checksum(packet, ip_size));
        remote_size = sizeof(*destination);
    }
    put32(tcp + 4, sequence);
    put32(tcp + 8, acknowledgment);
    tcp[12] = (tcp_size / 4) << 4;
    tcp[13] = 0x18;
    put16(tcp + 14, 65535);
    if (md5) { tcp[20] = 19; tcp[21] = 18; tcp[38] = tcp[39] = 1; }
    memcpy(tcp + tcp_size, payload, size);
    memcpy(pseudo + pseudo_size, tcp, tcp_size + size);
    put16(tcp + 16, checksum(pseudo, pseudo_size + tcp_size + size));
    int raw = socket(remote.ss_family, SOCK_RAW, IPPROTO_RAW);
    if (raw < 0) return false;
    int enabled = 1;
    int result = setsockopt(raw, v6 ? IPPROTO_IPV6 : IPPROTO_IP, v6 ? IPV6_HDRINCL : IP_HDRINCL, &enabled, sizeof(enabled));
    if (!result) {
        for (int attempt = 0; attempt < 3; attempt++) {
            if (sendto(raw, packet, total, 0, (void *)&remote, remote_size) != (ssize_t)total) { result = -1; break; }
        }
    }
    int saved = errno;
    close(raw);
    errno = saved;
    if (!result) usleep(10000);
    return result == 0;
}

bool raw_fake_supported(void)
{
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return false;
    int enabled = 1;
    int result = setsockopt(fd, IPPROTO_TCP, TCP_REPAIR, &enabled, sizeof(enabled));
    int saved = errno;
    close(fd);
    if (result) { errno = saved; return false; }
    fd = socket(AF_INET, SOCK_RAW, IPPROTO_RAW);
    if (fd < 0) return false;
    close(fd);
    return true;
}
