#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#include <fcntl.h>
#include <errno.h>
#include <termios.h>
#include <unistd.h>

#define LAPTIMER_COMM_PREAMBLE_BYTE 0xFC

#define LAPTIMER_COMM_FRAME_END_BYTE 0xFE

#define LAPTIMER_COMM_RESET_FRAME_U32 (0xFFFFFFFF)


typedef enum lcFrameType_e {
    E_LC_FRAME_TYPE_RI = 0x5A,
    E_LC_FRAME_TYPE_MSG = 0x5B
} lcFrameType_t;

typedef struct raceInfoChannelData_s {
    uint32_t pos     : 3; // up to 6 pilots
    uint32_t lap     : 4; // no more than 8 laps
    uint32_t secs    : 6; // 1 min
    uint32_t hunds   : 7; // 100 hundreds of second
    uint32_t started : 1; // start gate crossed
    uint32_t chn_idx : 4; // channel index 0-9, as in RACE_INFO_CHANNELS
    uint32_t rsvd    : 7;
} raceInfoChannelData_t;

typedef union {
    uint32_t u32;
    raceInfoChannelData_t data;
} raceInfoData_t;

int main(int argc, char **argv)
{
    raceInfoData_t raceInfo;
    if (argc < 6)
    {
	raceInfo.u32 = LAPTIMER_COMM_RESET_FRAME_U32;
    } else {
	printf("params\n");
	raceInfo.data.pos = atoi(argv[1]);
	raceInfo.data.lap = atoi(argv[2]);
	raceInfo.data.secs = atoi(argv[3]);
	raceInfo.data.hunds = atoi(argv[4]);

	raceInfo.data.started = atoi(argv[5]);
	raceInfo.data.chn_idx = atoi(argv[6]);
    }

    int serial_port = open("/dev/ttyUSB0", O_RDWR);

    if (serial_port < 0)
    {
	printf("Error %i from open: %s\n", errno, strerror(errno));
//	return -1;
    }

    struct termios tty;

    if(tcgetattr(serial_port, &tty) != 0) {
	printf("Error %i from tcgetattr: %s\n", errno, strerror(errno));
    }

    tty.c_cflag &= ~PARENB;
    tty.c_cflag &= ~CSTOPB;
    tty.c_cflag &= ~CSIZE;
    tty.c_cflag |= CS8;
    tty.c_cflag &= ~CRTSCTS;
    tty.c_cflag |= CREAD | CLOCAL;

    tty.c_lflag &= ~ICANON;
    tty.c_lflag &= ~ECHO;
    tty.c_lflag &= ~ECHOE;
    tty.c_lflag &= ~ECHONL;
    tty.c_lflag &= ~ISIG;

    tty.c_iflag &= ~(IXON | IXOFF | IXANY);
    tty.c_iflag &= ~(IGNBRK|BRKINT|PARMRK|ISTRIP|INLCR|IGNCR|ICRNL);

    tty.c_oflag &= ~OPOST;
    tty.c_oflag &= ~ONLCR;

    tty.c_cc[VTIME] = 10;
    tty.c_cc[VMIN] = 0;

    cfsetispeed(&tty, B9600);
    cfsetospeed(&tty, B9600);

    if (tcsetattr(serial_port, TCSANOW, &tty) != 0) {
	printf("Error %i from tcsetattr: %s\n", errno, strerror(errno));
    }


    unsigned char msg[8];
    msg[0] = LAPTIMER_COMM_PREAMBLE_BYTE;
    msg[1] = E_LC_FRAME_TYPE_RI;
    memcpy(msg + 2, &raceInfo, sizeof(raceInfo));
    msg[6] = LAPTIMER_COMM_FRAME_END_BYTE;
    int framePos = 0;
    unsigned char chksum = E_LC_FRAME_TYPE_RI;
    while (framePos < sizeof(raceInfo)) {
	chksum += msg[framePos + 2];
	framePos++;
    }
    chksum += LAPTIMER_COMM_FRAME_END_BYTE;
    msg[7] = chksum;
    printf("checksum %d\n", chksum);

    write(serial_port, msg, 8);

    close(serial_port);
}
