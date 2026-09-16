// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IncidentAnchor} from "../src/IncidentAnchor.sol";

// Deliberately forge-std-free so the compose init container can run it
// without installing libraries first.
interface Vm {
    function startBroadcast() external;
    function stopBroadcast() external;
}

contract Deploy {
    Vm private constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));

    function run() external returns (address) {
        vm.startBroadcast();
        IncidentAnchor anchor = new IncidentAnchor();
        vm.stopBroadcast();
        return address(anchor);
    }
}
