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

#define LC_RACE_MSG_LEN 6
#define LC_RACE_MSG_CHN_BCAST 0x0F

typedef enum lcFrameType_e {
    E_LC_FRAME_TYPE_RI = 0x5A,
    E_LC_FRAME_TYPE_MSG = 0x5B
} lcFrameType_t;

typedef struct raceMsgFlags_s {
    uint8_t seq_id    : 3;
    uint8_t chn_idx   : 4;
    uint8_t rsvd      : 1;
} raceMsgFlags_t;

typedef struct raceMsgData_s {
    raceMsgFlags_t flags;
    char msg[LC_RACE_MSG_LEN + 1]; // NULL terminated string
} raceMsgData_t;

int main(int argc, char **argv)
{
    raceMsgData_t raceMsg;

    strncpy(&raceMsg.msg[0], argv[1], LC_RACE_MSG_LEN);
    raceMsg.flags.seq_id = atoi(argv[2]);
    if (argc < 4)
    {
	printf("broadcast\n");
	raceMsg.flags.chn_idx = LC_RACE_MSG_CHN_BCAST;
    } else {
	printf("channel\n");
	raceMsg.flags.chn_idx = atoi(argv[3]);
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


    unsigned char msg[12];
    msg[0] = LAPTIMER_COMM_PREAMBLE_BYTE;
    msg[1] = E_LC_FRAME_TYPE_MSG;
    memcpy(msg + 2, &raceMsg, sizeof(raceMsg));
    printf("%d\n", sizeof(raceMsg));
    msg[10] = LAPTIMER_COMM_FRAME_END_BYTE;
    int framePos = 0;
    unsigned char chksum = E_LC_FRAME_TYPE_MSG;
    while (framePos < sizeof(raceMsg)) {
	chksum += msg[framePos + 2];
	framePos++;
    }
    chksum += LAPTIMER_COMM_FRAME_END_BYTE;
    msg[11] = chksum;
    printf("payload: ");
    for (int i = 0; i < 12; i++)
	printf("%02x ", msg[i]);
    printf("\n");
    printf("checksum %d\n", chksum);

    write(serial_port, msg, 12);

    close(serial_port);
}
