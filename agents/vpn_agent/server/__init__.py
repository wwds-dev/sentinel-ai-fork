"""
server — the VPN server side of VPN Agent.

Everything here builds and operates a VPN server you own: it generates the
crypto material locally, renders server and client configuration, and applies
it to a target host either natively (hardware on your LAN) or remotely over SSH.

Private keys are generated on this machine and never travel except inside the
config files that are written to the server over an encrypted channel.
"""
