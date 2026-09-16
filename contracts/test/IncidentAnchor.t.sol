// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import {IncidentAnchor} from "../src/IncidentAnchor.sol";

contract IncidentAnchorTest is Test {
    IncidentAnchor internal anchor;
    address internal stranger = address(0xBEEF);

    event Anchored(
        uint256 indexed batchId,
        bytes32 root,
        uint64 firstEventId,
        uint64 lastEventId,
        uint256 timestamp
    );

    function setUp() public {
        anchor = new IncidentAnchor();
    }

    function testAnchorStoresBatch() public {
        bytes32 root = keccak256("root-1");
        uint256 id = anchor.anchor(root, 1, 10);
        assertEq(id, 0);
        (bytes32 r, uint64 first, uint64 last, uint256 ts) = anchor.getBatch(0);
        assertEq(r, root);
        assertEq(first, 1);
        assertEq(last, 10);
        assertEq(ts, block.timestamp);
        assertEq(anchor.batchCount(), 1);
    }

    function testAnchorEmitsEvent() public {
        bytes32 root = keccak256("root-ev");
        vm.expectEmit(true, false, false, true);
        emit Anchored(0, root, 1, 5, block.timestamp);
        anchor.anchor(root, 1, 5);
    }

    function testSequentialBatchIds() public {
        assertEq(anchor.anchor(keccak256("a"), 1, 10), 0);
        assertEq(anchor.anchor(keccak256("b"), 11, 20), 1);
        assertEq(anchor.anchor(keccak256("c"), 21, 21), 2);
        assertEq(anchor.batchCount(), 3);
    }

    function testOnlyOwnerCanAnchor() public {
        vm.prank(stranger);
        vm.expectRevert(IncidentAnchor.NotOwner.selector);
        anchor.anchor(keccak256("x"), 1, 2);
    }

    function testRejectsInvertedRange() public {
        vm.expectRevert(IncidentAnchor.InvalidRange.selector);
        anchor.anchor(keccak256("x"), 10, 5);
    }

    function testRejectsOverlappingHistory() public {
        anchor.anchor(keccak256("a"), 1, 10);
        vm.expectRevert(IncidentAnchor.InvalidRange.selector);
        anchor.anchor(keccak256("b"), 10, 20);
        vm.expectRevert(IncidentAnchor.InvalidRange.selector);
        anchor.anchor(keccak256("c"), 5, 8);
    }

    function testOwnershipTransfer() public {
        anchor.transferOwnership(stranger);
        assertEq(anchor.owner(), stranger);
        vm.expectRevert(IncidentAnchor.NotOwner.selector);
        anchor.anchor(keccak256("x"), 1, 2);
        vm.prank(stranger);
        anchor.anchor(keccak256("x"), 1, 2);
    }

    function testOwnershipTransferRejectsZero() public {
        vm.expectRevert(IncidentAnchor.ZeroAddress.selector);
        anchor.transferOwnership(address(0));
    }

    function testGetBatchOutOfRangeReverts() public {
        vm.expectRevert();
        anchor.getBatch(0);
    }
}
