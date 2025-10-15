# Диапазон выдаваемых IP
dhcp-range=${node.dnsmasq.ip_range},${node.dnsmasq.mask}

# Опция: шлюз
dhcp-option=3,${node.dnsmasq.gw}

# PID-файл
pid-file=${node.dnsmasq.pid_file}

# Отключить DNS (порт 53)
port=0

# Указываем интерфейсы, на которых будет слушать
% for intf in node.dnsmasq.interfaces:
interface=${intf}
% endfor

# Логирование DHCP-запросов
log-queries
log-dhcp

# Слушать ТОЛЬКО на указанных интерфейсах
bind-interfaces

no-daemon
