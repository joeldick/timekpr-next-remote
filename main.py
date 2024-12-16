# Press Shift+F10 to execute it or replace it with your code.
# Press Double Shift to search everywhere for classes, files, tool windows, actions, and settings.

import conf, re, humanize
from fabric import Connection
from paramiko.ssh_exception import AuthenticationException
from paramiko.ssh_exception import NoValidConnectionsError
from gotify import Gotify
from threading import Lock

# Global dictionary to cache SSH connections
ssh_connections = {}
ssh_locks = {}

def get_config():
    return conf.trackme


def send_alert(user, action, seconds, computer, ssh):
    for alerts in conf.gotify:
        if alerts['enabled'] is True:
            gotify = Gotify(
                base_url = alerts['url'],
                app_token= alerts['token'],
            )
            try:
                usage = get_usage(user, computer, ssh)
                added = humanize.naturaldelta(seconds)
                unused = humanize.precisedelta(usage['time_left'])
                used = humanize.precisedelta(usage['time_spent'])
                result = gotify.create_message(
                    f"{action} {added}, {unused} unused, {used} used :)",
                    title=f"Timekpr: {user} {action} time",
                    priority=2,
                )
            except Exception as e:
                print(f"Failed to call Gotify. Config is: {alerts}.  Error is: {e}")
                continue
            print(f"Gotify alert sent to {alerts['url']}")
    return True


def get_usage(user, computer, ssh=None):
    global timekpra_userinfo_output
    fail_json = {'time_left': 0, 'time_spent': 0, 'result': 'fail'}

    # Use the provided SSH connection or fetch a new one
    ssh = ssh or get_connection(computer)
    if ssh is None:
        return fail_json

    try:
        with ssh_locks[computer]:  # Serialize commands for this host
            timekpra_userinfo_output = str(ssh.run(
                conf.ssh_timekpra_bin + ' --userinfo ' + user,
                hide=True
            ))
    except Exception as e:
        print(f"Failed to get usage for {user} on {computer}: {e}")
        return fail_json

    # Parse the output for time left and time spent
    time_left_match = re.search(r"(TIME_LEFT_DAY: )([0-9]+)", timekpra_userinfo_output)
    time_spent_match = re.search(r"(TIME_SPENT_DAY: )([0-9]+)", timekpra_userinfo_output)

    if not time_left_match or not time_spent_match:
        print(f"Error parsing time data for {user} on {computer}. Output: {timekpra_userinfo_output}")
        return fail_json

    time_left = time_left_match.group(2)
    time_spent = time_spent_match.group(2)
    print(f"Time left for {user} on {computer}: {time_left} seconds")
    return {'time_left': time_left, 'time_spent': time_spent, 'result': 'success'}



def get_connection(computer):
    global ssh_connections, ssh_locks

    # Initialize lock for the computer if not already done
    if computer not in ssh_locks:
        ssh_locks[computer] = Lock()

    # Check if we already have a connection for this computer
    if computer in ssh_connections and ssh_connections[computer].is_connected:
        return ssh_connections[computer]

    # Establish a new connection if not already connected
    connect_kwargs = {
        'allow_agent': False,
        'look_for_keys': False,
        "password": conf.ssh_password
    }
    try:
        connection = Connection(
            host=computer,
            port=conf.ssh_port,
            user=conf.ssh_user,
            connect_kwargs=connect_kwargs
        )
        ssh_connections[computer] = connection
        print(f"Established new connection to {computer}")
        return connection
    except AuthenticationException as e:
        print(f"Wrong credentials for user '{conf.ssh_user}' on host '{computer}'. Check conf.py.")
    except NoValidConnectionsError as e:
        print(f"Cannot connect to SSH server on host '{computer}'. Check address or port in conf.py.")
    except Exception as e:
        print(f"Error establishing connection to '{computer}': {e}")

    return None  # Return None if connection fails


def adjust_time(up_down_string, seconds, ssh, user, computer):
    command = conf.ssh_timekpra_bin + ' --settimeleft ' + user + ' ' + up_down_string + ' ' + str(seconds)
    ssh.run(command)
    if up_down_string == '-':
        action = "removed"
    else:
        action = "added"
    print(f"{action} {seconds} for user '{user}'")
    try:
        send_alert(user, action, seconds, computer, ssh)
    except Exception as e:
        print(f"Failed to send alert: {e}")
    # todo - return false if this fails
    return True


def increase_time(seconds, ssh, user, computer):
    return adjust_time('+', seconds, ssh, user, computer)


def decrease_time(seconds, ssh, user, computer):
    return adjust_time('-', seconds, ssh, user, computer)