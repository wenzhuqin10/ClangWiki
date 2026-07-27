#ifndef CLANGWIKI_NETWORK_H
#define CLANGWIKI_NETWORK_H

typedef struct {
  const char *address;
  unsigned short port;
} network_config_t;

int network_init(const network_config_t *config);
void network_shutdown(void);

#endif

