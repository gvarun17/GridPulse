"""Modbus TCP stub (docker mode only, requires pymodbus).

Exposes simulator profiles as Modbus holding registers so edge.py can
poll a *real* Modbus server instead of calling the simulator in-process:
  register 0: chiller-01 power (kW x 10)
  register 1: chiller-02 power (kW x 10)
  register 2: grid power (kW x 10)
This is a teaching stub, not a certified meter gateway: register maps in
real life come from the meter manufacturer's manual, and getting one
register wrong is the classic brownfield bug. See README §6.
"""
# To run (in docker / with pymodbus installed):
#   from pymodbus.server import StartTcpServer
#   from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
#   store = ModbusSlaveContext(hr=ModbusSequentialDataBlock(0, [0]*10))
#   StartTcpServer(context=ModbusServerContext(slaves=store, single=True), address=("0.0.0.0", 5020))
print("modbus_stub: see docstring — install pymodbus and uncomment the server block to run.")
