import pyvisa

def main():
    # 创建资源管理器
    rm = pyvisa.ResourceManager()
    
    # 列出所有连接的仪器
    resources = rm.list_resources()
    print("已连接的仪器:")
    for res in resources:
        print(f"  - {res}")
    
    if not resources:
        print("未检测到仪器")
        return
    
    # 连接到第一个仪器(请按实际情况修改地址)
    # 常见地址格式:
    #   USB:    'USB0::0x1234::0x5678::SERIAL::INSTR'
    #   GPIB:   'GPIB0::5::INSTR'
    #   TCP/IP: 'TCPIP0::192.168.1.100::INSTR'
    
    instrument_address = resources[-1]
    instrument= None
    try:
        instrument = rm.open_resource(instrument_address)
        instrument.timeout = 5000  # 超时 5 秒
        
        # 查询仪器身份(SCPI 标准命令)
        idn = instrument.query('*IDN?')
        print(f"\n仪器信息: {idn.strip()}")
        
        # 复位仪器
        instrument.write('*RST')
        
        # 示例:读取测量值(以万用表为例)
        # voltage = instrument.query('MEAS:VOLT:DC?')
        # print(f"电压测量值: {voltage.strip()} V")
        
    except pyvisa.VisaIOError as e:
        print(f"通信错误: {e}")
    finally:
        if instrument:
            instrument.close()
            rm.close()

if __name__ == '__main__':
    main()